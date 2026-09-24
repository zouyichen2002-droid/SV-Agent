-- SV-Agent · M0-04「导出现状」（只读，不改工程）
--
-- 把 SynthV 眼里的当前工程写成 JSON：速度、拍号、每条轨道主音符组里的每一个音
-- （起点、时值、音高、歌词）。写到工程文件旁边：<工程文件>.dump.json
--
-- 为什么要它：SynthV 的官方脚本接口不能打开、保存、导出工程（官方脚本手册确认），
-- 但能读「当前打开的工程」。所以验证「我们写的 .svp 对不对」只能这样做：
-- 你在 SynthV 里打开我们写的文件 → 运行这个脚本 → 我们拿它的输出和写进去的比。
--
-- 用到的接口方法名，全部在上游 SynthV Agent Bridge 0.3.1 里出现过（它在 SynthV 2.1.2+ 实测过）。

function getClientInfo()
  return {
    name = "SV-Agent 导出现状（M0-04）",
    category = "SV-Agent",
    author = "SV-Agent",
    versionNumber = 1,
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
  w('{"fileName":' .. str(path) .. ',"tempo":[')
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
    w('{"name":' .. str(track:getName()) .. ',"notes":[')
    local group = track:getGroupReference(1):getTarget()
    for n = 1, group:getNumNotes() do
      local note = group:getNote(n)
      if n > 1 then w(',') end
      w('{"onset":' .. num(note:getOnset()) .. ',"duration":' .. num(note:getDuration()) ..
        ',"pitch":' .. num(note:getPitch()) .. ',"lyrics":' .. str(note:getLyrics()) .. '}')
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
