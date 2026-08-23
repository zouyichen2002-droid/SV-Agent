"""RMVPE 网络结构。

**这份结构不是凭记忆写的，是从 `rmvpe.pt` 的 741 个权重键与形状反推的**：

    unet.encoder.bn                        BatchNorm2d(1)
    unet.encoder.layers.{0..4}             ResEncoderBlock, 通道 1→16→32→64→128→256
      .conv.{0..3}                         每层 4 个 ConvBlockRes
        .conv.{0,1,3,4}                    Conv2d(bias=False), BN, [ReLU], Conv2d, BN, [ReLU]
        .shortcut                          只在通道变化的那个 block 上出现（带 bias）
    unet.intermediate.layers.{0..3}        ResEncoderBlock，256→512 然后 512→512 ×3，不池化
    unet.decoder.layers.{0..4}             ResDecoderBlock，512→256→128→64→32→16
      .conv1.{0,1}                         ConvTranspose2d(bias=False), BN, [ReLU]
      .conv2.{0..3}                        4 个 ConvBlockRes，第 0 个入通道是 out*2（拼 skip）
    cnn                                    Conv2d(16, 3, 3, padding=1)
    fc.0.gru                               BiGRU  in=384(=3×128 mel), hidden=256, 1 层
    fc.1                                   Linear(512, 360)   360 = 20 音分 × 360 bins

正确性靠两道验证，见 rmvpe_est.py 的 self_check()：
1. `load_state_dict(strict=True)` 零缺失 / 零多余键 —— 结构对不上会直接报错
2. 合成正弦的绝对真值 —— mel 参数或 cents 映射常数写错会立刻显形（这类错误不报异常，
   只是静默输出偏掉的 f0，属 ADR-0001 里点名的最危险失败类型）
"""
from __future__ import annotations

import torch
import torch.nn as nn


class ConvBlockRes(nn.Module):
    def __init__(self, in_ch: int, out_ch: int, momentum: float = 0.01):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, (3, 3), (1, 1), (1, 1), bias=False),
            nn.BatchNorm2d(out_ch, momentum=momentum),
            nn.ReLU(),
            nn.Conv2d(out_ch, out_ch, (3, 3), (1, 1), (1, 1), bias=False),
            nn.BatchNorm2d(out_ch, momentum=momentum),
            nn.ReLU(),
        )
        self.is_shortcut = in_ch != out_ch
        if self.is_shortcut:
            self.shortcut = nn.Conv2d(in_ch, out_ch, (1, 1), (1, 1), (0, 0))

    def forward(self, x):
        return self.conv(x) + (self.shortcut(x) if self.is_shortcut else x)


class ResEncoderBlock(nn.Module):
    def __init__(self, in_ch: int, out_ch: int, kernel_size, n_blocks: int = 1,
                 momentum: float = 0.01):
        super().__init__()
        self.n_blocks = n_blocks
        self.conv = nn.ModuleList([ConvBlockRes(in_ch, out_ch, momentum)])
        for _ in range(n_blocks - 1):
            self.conv.append(ConvBlockRes(out_ch, out_ch, momentum))
        self.kernel_size = kernel_size
        if kernel_size is not None:
            self.pool = nn.AvgPool2d(kernel_size=kernel_size)

    def forward(self, x):
        for i in range(self.n_blocks):
            x = self.conv[i](x)
        if self.kernel_size is not None:
            return x, self.pool(x)
        return x


class Encoder(nn.Module):
    def __init__(self, in_ch, in_size, n_encoders, kernel_size, n_blocks,
                 out_ch=16, momentum=0.01):
        super().__init__()
        self.n_encoders = n_encoders
        self.bn = nn.BatchNorm2d(in_ch, momentum=momentum)
        self.layers = nn.ModuleList()
        self.latent_channels = []
        for _ in range(n_encoders):
            self.layers.append(ResEncoderBlock(in_ch, out_ch, kernel_size, n_blocks, momentum))
            self.latent_channels.append([out_ch, in_size])
            in_ch = out_ch
            out_ch *= 2
            in_size //= 2
        self.out_size = in_size
        self.out_channel = out_ch // 2

    def forward(self, x):
        concat = []
        x = self.bn(x)
        for i in range(self.n_encoders):
            t, x = self.layers[i](x)
            concat.append(t)
        return x, concat


class Intermediate(nn.Module):
    def __init__(self, in_ch, out_ch, n_inters, n_blocks, momentum=0.01):
        super().__init__()
        self.n_inters = n_inters
        self.layers = nn.ModuleList([ResEncoderBlock(in_ch, out_ch, None, n_blocks, momentum)])
        for _ in range(n_inters - 1):
            self.layers.append(ResEncoderBlock(out_ch, out_ch, None, n_blocks, momentum))

    def forward(self, x):
        for i in range(self.n_inters):
            x = self.layers[i](x)
        return x


class ResDecoderBlock(nn.Module):
    def __init__(self, in_ch, out_ch, stride, n_blocks=1, momentum=0.01,
                 concat_order="up_first"):
        super().__init__()
        out_padding = (0, 1) if stride == (1, 2) else (1, 1)
        self.n_blocks = n_blocks
        self.concat_order = concat_order
        self.conv1 = nn.Sequential(
            nn.ConvTranspose2d(in_ch, out_ch, (3, 3), stride, (1, 1),
                               output_padding=out_padding, bias=False),
            nn.BatchNorm2d(out_ch, momentum=momentum),
            nn.ReLU(),
        )
        self.conv2 = nn.ModuleList([ConvBlockRes(out_ch * 2, out_ch, momentum)])
        for _ in range(n_blocks - 1):
            self.conv2.append(ConvBlockRes(out_ch, out_ch, momentum))

    def forward(self, x, concat_tensor):
        x = self.conv1(x)
        # 拼接顺序权重形状分辨不出来（两边通道数相同），必须实测确定。
        # 判据见 scripts/identify_rmvpe_forward.py：重采样自洽性。
        if self.concat_order == "up_first":
            x = torch.cat((x, concat_tensor), dim=1)
        else:
            x = torch.cat((concat_tensor, x), dim=1)
        for i in range(self.n_blocks):
            x = self.conv2[i](x)
        return x


class Decoder(nn.Module):
    def __init__(self, in_ch, n_decoders, stride, n_blocks, momentum=0.01,
                 concat_order="up_first"):
        super().__init__()
        self.layers = nn.ModuleList()
        self.n_decoders = n_decoders
        for _ in range(n_decoders):
            out_ch = in_ch // 2
            self.layers.append(ResDecoderBlock(in_ch, out_ch, stride, n_blocks,
                                               momentum, concat_order))
            in_ch = out_ch

    def forward(self, x, concat):
        for i in range(self.n_decoders):
            x = self.layers[i](x, concat[-1 - i])
        return x


class DeepUnet(nn.Module):
    def __init__(self, kernel_size, n_blocks, en_de_layers=5, inter_layers=4,
                 in_ch=1, en_out_ch=16, concat_order="up_first"):
        super().__init__()
        self.encoder = Encoder(in_ch, 128, en_de_layers, kernel_size, n_blocks, en_out_ch)
        # 通道数按权重形状定，不按直觉：
        #   encoder 末层输出 256（unet.encoder.layers.4 → 256）
        #   intermediate 是 256→512（unet.intermediate.layers.0.conv.0.shortcut = (512,256,1,1)）
        #   decoder 从 512 起，512→256→128→64→32→16（conv1 权重 (512,256,3,3) 起）
        enc_out = self.encoder.out_channel          # 256
        self.intermediate = Intermediate(enc_out, enc_out * 2, inter_layers, n_blocks)
        self.decoder = Decoder(enc_out * 2, en_de_layers, kernel_size, n_blocks,
                               concat_order=concat_order)

    def forward(self, x):
        x, concat = self.encoder(x)
        x = self.intermediate(x)
        return self.decoder(x, concat)


class BiGRU(nn.Module):
    def __init__(self, input_features, hidden_features, num_layers):
        super().__init__()
        self.gru = nn.GRU(input_features, hidden_features, num_layers=num_layers,
                          batch_first=True, bidirectional=True)

    def forward(self, x):
        return self.gru(x)[0]


class E2E(nn.Module):
    """RMVPE 主网络。E2E(n_blocks=4, n_gru=1, kernel_size=(2,2)) 对应 rmvpe.pt。"""

    def __init__(self, n_blocks=4, n_gru=1, kernel_size=(2, 2),
                 en_de_layers=5, inter_layers=4, in_ch=1, en_out_ch=16,
                 concat_order="up_first", flatten_mode="channel_major",
                 input_layout="time_rows"):
        super().__init__()
        # 这三个开关都是"权重形状无法区分"的前向选择，默认值由实测确定，
        # 见 scripts/identify_rmvpe_forward.py。
        self.flatten_mode = flatten_mode
        self.input_layout = input_layout
        self.unet = DeepUnet(kernel_size, n_blocks, en_de_layers, inter_layers,
                             in_ch, en_out_ch, concat_order=concat_order)
        self.cnn = nn.Conv2d(en_out_ch, 3, (3, 3), padding=(1, 1))
        if n_gru:
            self.fc = nn.Sequential(
                BiGRU(3 * 128, 256, n_gru),
                nn.Linear(512, 360),
                nn.Dropout(0.25),
                nn.Sigmoid(),
            )
        else:
            self.fc = nn.Sequential(nn.Linear(3 * 128, 360), nn.Dropout(0.25), nn.Sigmoid())

    def forward(self, mel):
        """mel: (B, n_mels, T) → (B, T, 360)。"""
        if self.input_layout == "time_rows":
            x = mel.transpose(-1, -2).unsqueeze(1)        # (B, 1, T, n_mels)
        else:
            x = mel.unsqueeze(1)                          # (B, 1, n_mels, T)
        x = self.cnn(self.unet(x))                        # (B, 3, A, B)
        if self.input_layout != "time_rows":
            x = x.transpose(-1, -2)                       # 把时间轴换回倒数第二维
        if self.flatten_mode == "channel_major":
            x = x.transpose(1, 2).flatten(-2)             # (B, T, 3*n_mels) 通道在外
        else:
            x = x.permute(0, 2, 3, 1).flatten(-2)         # (B, T, n_mels*3) 频率在外
        return self.fc(x)
