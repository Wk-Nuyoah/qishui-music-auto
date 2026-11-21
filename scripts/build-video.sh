#!/usr/bin/env bash
# 抖音竖屏演示视频合成 v2：上录屏下日志终端布局（1080x1920, ~62s）
# 依赖: ffmpeg (winget 版路径见 FF)、参考项目 assets/voice/q/*.mp3、参考项目 assets/bgm.mp3
# 录屏母带: D:/software/qishui-auto/demo_auto2.mp4 (720x1280, 不进仓库)
# 用法: bash scripts/build-video.sh
set -e

FF="/c/Users/weikang/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin/ffmpeg.exe"
F="C\\:/Windows/Fonts/msyhbd.ttc"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
A="$ROOT/assets"
T="$A/build"
REF="/d/workspace/code/java/weikang/github-trending-daily"   # 配音/BGM 来源（build-voice.py 产物）
SRC="/d/software/qishui-auto/demo_auto2.mp4"                 # 录屏母带
mkdir -p "$T"

# 布局：录屏 720x1280 等比缩到 540x960，居中贴在上半屏，下半屏为日志终端（纯黑）
LAYOUT="scale=540:960,pad=1080:1920:270:0:black"

# 1. 开场卡 4s
$FF -y -v error -f lavfi -i color=c=black:s=1080x1920:d=4 \
  -vf "drawtext=fontfile='$F':text='让手机自己看广告':fontsize=88:fontcolor=white:x=(w-text_w)/2:y=h/2-100,drawtext=fontfile='$F':text='汽水音乐 · 全自动领免费时长':fontsize=44:fontcolor=0xAAAAAA:x=(w-text_w)/2:y=h/2+60" \
  -c:v libx264 -crf 23 -preset fast -pix_fmt yuv420p "$T/01_intro.mp4"

# 2. 录屏段1 30s（一轮完整循环：领取成功 → 领取奖励 → 下一广告）
$FF -y -v error -ss 93 -t 30 -i "$SRC" -vf "$LAYOUT,fps=25" \
  -c:v libx264 -crf 23 -preset fast -pix_fmt yuv420p -an "$T/02_loop1.mp4"

# 3. 原理卡 3s
$FF -y -v error -f lavfi -i color=c=0x111111:s=1080x1920:d=3 \
  -vf "drawtext=fontfile='$F':text='截屏  →  OCR 认字  →  模拟点击':fontsize=58:fontcolor=white:x=(w-text_w)/2:y=h/2-40,drawtext=fontfile='$F':text='循环往复，无人值守':fontsize=40:fontcolor=0x00E676:x=(w-text_w)/2:y=h/2+80" \
  -c:v libx264 -crf 23 -preset fast -pix_fmt yuv420p "$T/03_principle.mp4"

# 4. 录屏段2 快放 2x（15s）
$FF -y -v error -ss 55 -t 30 -i "$SRC" -vf "$LAYOUT,setpts=0.5*PTS,fps=25" \
  -c:v libx264 -crf 23 -preset fast -pix_fmt yuv420p -an "$T/04_loop2_fast.mp4"

# 5. 直播间卡 6s
$FF -y -v error -loop 1 -t 6 -i "$A/screenshots/07-live-room.jpg" \
  -vf "$LAYOUT" \
  -c:v libx264 -crf 23 -preset fast -pix_fmt yuv420p "$T/05_liveroom.mp4"

# 6. 结尾卡 4s
$FF -y -v error -f lavfi -i color=c=black:s=1080x1920:d=4 \
  -vf "drawtext=fontfile='$F':text='代码已开源':fontsize=80:fontcolor=white:x=(w-text_w)/2:y=h/2-90,drawtext=fontfile='$F':text='GitHub 搜 qishui-music-auto':fontsize=46:fontcolor=0x00E676:x=(w-text_w)/2:y=h/2+60" \
  -c:v libx264 -crf 23 -preset fast -pix_fmt yuv420p "$T/06_outro.mp4"

# 7. 拼接（4+30+3+15+6+4 = 62s）
cd "$T"
printf "file '01_intro.mp4'\nfile '02_loop1.mp4'\nfile '03_principle.mp4'\nfile '04_loop2_fast.mp4'\nfile '05_liveroom.mp4'\nfile '06_outro.mp4'\n" > list.txt
$FF -y -v error -f concat -safe 0 -i list.txt -c copy base.mp4

# 8. 叠日志终端字幕（复制到 build 目录用相对路径，避免 filter 解析盘符冒号）
cp "$ROOT/scripts/log.ass" "$T/log.ass"
$FF -y -v error -i base.mp4 -vf "ass=log.ass" \
  -c:v libx264 -profile:v main -level 4.0 -crf 23 -preset fast -pix_fmt yuv420p -movflags +faststart voiced.mp4

# 9. 配音 + BGM 混音
#    q00-q02 连播(开场+进广告)，q03 领取成功 22s，q04 领取奖励 26s，q05 原理 34.5s，
#    q07 无人值守 38s，q06 直播间 52.8s，q08 连直播间 56.8s，q09 结尾 58.8s
cd "$REF/assets/voice/q"
printf "file 'q00.mp3'\nfile 'q01.mp3'\nfile 'q02.mp3'\n" > list3.txt
$FF -y -v error -i "$T/voiced.mp4" -f concat -safe 0 -i list3.txt \
  -i q03.mp3 -i q04.mp3 -i q05.mp3 -i q07.mp3 -i q06.mp3 -i q08.mp3 -i q09.mp3 \
  -i "$REF/assets/bgm.mp3" \
  -filter_complex "\
[1:a]aresample=48000,aformat=channel_layouts=mono,adelay=500|500[a0];\
[2:a]aresample=48000,aformat=channel_layouts=mono,adelay=22000|22000[a3];\
[3:a]aresample=48000,aformat=channel_layouts=mono,adelay=26000|26000[a4];\
[4:a]aresample=48000,aformat=channel_layouts=mono,adelay=34500|34500[a5];\
[5:a]aresample=48000,aformat=channel_layouts=mono,adelay=38000|38000[a7];\
[6:a]aresample=48000,aformat=channel_layouts=mono,adelay=52800|52800[a6];\
[7:a]aresample=48000,aformat=channel_layouts=mono,adelay=56800|56800[a8];\
[8:a]aresample=48000,aformat=channel_layouts=mono,adelay=58800|58800[a9];\
[9:a]aresample=48000,aformat=channel_layouts=mono,volume=0.28[bgm];\
[a0][a3][a4][a5][a7][a6][a8][a9]amix=inputs=8:duration=longest:dropout_transition=0:normalize=0[vo];\
[vo][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -ar 44100 -ac 2 -b:a 192k \
  -brand mp42 -movflags +faststart "$A/douyin-demo.mp4"

echo "OK -> $A/douyin-demo.mp4"
