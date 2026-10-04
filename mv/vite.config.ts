// SV-Agent（10-03）：照 pdoom-video 的 vite 配置改。歌曲数据和字体都在仓库外：
//   /song/*  → MV_SONG_DIR（那首歌的 MV 文件夹：audio.wav、lyrics.json、audio.json；第三方的歌、歌词不进仓库）
//   /fonts/* → MV_FONT_DIR（默认 E:/sv-agent-data/fonts；字体文件不进仓库）
// MV_NO_HMR=1：不热更新（导出途中改了文件也不能让页面重载）
import { defineConfig, normalizePath, type Plugin } from 'vite';
import path from 'node:path';

const songDir = process.env.MV_SONG_DIR ? path.resolve(process.env.MV_SONG_DIR) : '';
const fontDir = path.resolve(process.env.MV_FONT_DIR ?? 'E:/sv-agent-data/fonts');
const mounts: [string, string][] = [['/song/', songDir], ['/fonts/', fontDir]];

function outsideAssets(): Plugin {
  return {
    name: 'outside-assets',
    configureServer(server) {
      if (!songDir) server.config.logger.warn('MV_SONG_DIR 没设：/song/ 读不到（先设成那首歌的 MV 文件夹）');
      server.middlewares.use((req, _res, next) => {
        for (const [prefix, dir] of mounts) {
          if (dir && req.url?.startsWith(prefix)) {
            req.url = `/@fs/${encodeURI(normalizePath(dir))}/${req.url.slice(prefix.length)}`;
            break;
          }
        }
        next();
      });
    },
  };
}

export default defineConfig({
  root: '.',
  publicDir: false,
  plugins: [outsideAssets()],
  server: {
    port: 5173,
    strictPort: false,
    hmr: process.env.MV_NO_HMR ? false : undefined,
    fs: { allow: ['.', fontDir, ...(songDir ? [songDir] : [])] },
  },
  build: { target: 'esnext', assetsInlineLimit: 0 },
});
