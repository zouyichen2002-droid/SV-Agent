-- SV-Agent · M0-04「导出现状」（只读，不改工程）· 第 2 版
--
-- 把 SynthV 眼里的当前工程写成 JSON：速度、拍号、每条轨道上**所有音符组**里的每一个音
-- （绝对起点、时值、绝对音高、歌词，以及它属于哪个组、是不是主组）。
-- 写到工程文件旁边：<工程文件>.dump.json
--
-- 为什么要它：SynthV 的官方脚本接口不能打开、保存、导出工程（官方脚本手册确认），
-- 但能读「当前打开的工程」。所以验证「我们写的 .svp 对不对」只能这样做：
-- 你在 SynthV 里打开我们写的文件 → 运行这个脚本 → 我们拿它的输出和写进去的比。
--
-- 第 1 版的错（2026-09-26 实测抓到）：只读了主音符组（getGroupReference(1)），读出 0 个音。
-- 实际上 SynthV 2.2.1 打开工程时，把主音符组里的音**挪进了一个新建的音符组**，轨道再引用它。
-- 导出的 WAV 却唱了 7.4 秒 —— 两个裁判对不上，才查出是这个脚本错了。
-- 现在遍历全部引用，位置按「音符本地起点 + 引用的时间偏移」换算（和上游桥的算法一致）。
--
-- 用到的接口方法名，全部在上游 SynthV Agent Bridge 0.3.1 里出现过（它在 SynthV 2.1.2+ 实测过）。

function getClientInfo()
  return {
    name = "SV-Agent 导出现状（M0-04）",
    category = "SV-Agent",
    author = "SV-Agent",
    versionNumber = 2,
    minEditorVersion = 131330 -- Synthesizer V Studio 2.1.2
  }
end

local function str(s)
  s = string.gsub(s, '[%c"\\]', function(c)
    if c == '"' then return '\\"' end
    if c == '\\' then return '\\\\' end
    if c == '\n' then return '\\n' end
    if c == '\r' then return '\\r' end
    if c == '\t' then return '\\t' end
    return string.format('\\u%04x', string.byte(c))
  end)
  return '"' .. s .. '"'
end

local function num(x)
  if x == math.floor(x) and math.abs(x) < 2 ^ 53 then
    return string.format("%d", x)
  end
  return string.format("%.17g", x)
end

local function trackNotes(track)
  local notes = {}
  for r = 1, track:getNumGroups() do
    local ref = track:getGroupReference(r)
    local group = ref:getTarget()
    if group and not ref:isInstrumental() then
      for n = 1, group:getNumNotes() do
        local note = group:getNote(n)
        notes[#notes + 1] = {
          onset = note:getOnset() + ref:getTimeOffset(),
          duration = note:getDuration(),
          pitch = note:getPitch() + ref:getPitchOffset(),
          lyrics = note:getLyrics(),
          group = group:getName(),
          main = ref:isMain()
        }
      end
    end
  end
  table.sort(notes, function(a, b) return a.onset < b.onset end)
  return notes
end

function main()
  local project = SV:getProject()
  local path = project:getFileName()
  if path == nil or path == "" then
    SV:showMessageBox("SV-Agent", "这个工程还没保存过，没有路径可写。")
    SV:finish()
    return
  end

  local out = {}
  local function w(s) out[#out + 1] = s end

  local axis = project:getTimeAxis()
  w('{"script":2,"fileName":' .. str(path) .. ',"tempo":[')
  local tempos = axis:getAllTempoMarks()
  for i = 1, #tempos do
    if i > 1 then w(',') end
    w('{"position":' .. num(tempos[i].position) .. ',"bpm":' .. num(tempos[i].bpm) .. '}')
  end
  w('],"meter":[')
  local meters = axis:getAllMeasureMarks()
  for i = 1, #meters do
    if i > 1 then w(',') end
    w('{"position":' .. num(meters[i].position) .. ',"numerator":' .. num(meters[i].numerator) ..
      ',"denominator":' .. num(meters[i].denominator) .. '}')
  end
  w('],"tracks":[')
  for t = 1, project:getNumTracks() do
    local track = project:getTrack(t)
    if t > 1 then w(',') end
    w('{"name":' .. str(track:getName()) .. ',"groupRefs":' .. num(track:getNumGroups()) .. ',"notes":[')
    local notes = trackNotes(track)
    for i, nt in ipairs(notes) do
      if i > 1 then w(',') end
      w('{"onset":' .. num(nt.onset) .. ',"duration":' .. num(nt.duration) .. ',"pitch":' .. num(nt.pitch) ..
        ',"lyrics":' .. str(nt.lyrics) .. ',"group":' .. str(nt.group) .. ',"main":' .. tostring(nt.main) .. '}')
    end
    w(']}')
  end
  w(']}')

  local dumpPath = path .. ".dump.json"
  local f, err = io.open(dumpPath, "wb")
  if not f then
    SV:showMessageBox("SV-Agent", "写不出文件：" .. tostring(err))
  else
    f:write(table.concat(out))
    f:close()
    SV:showMessageBox("SV-Agent", "已导出：\n" .. dumpPath)
  end
  SV:finish()
end
