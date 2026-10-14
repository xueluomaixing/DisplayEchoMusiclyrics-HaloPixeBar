/*
 * Halo PixelBar 歌词桥 —— EchoMusic 插件
 *
 * 职责非常单一：
 *   1. 订阅 ctx.nowPlaying 快照（当前歌曲 + 歌词行 + 播放进度）
 *   2. 在 127.0.0.1 上开一个本地 HTTP / WebSocket 服务
 *   3. 把快照推给同机的 Halo PixelBar 同步程序
 *
 * 本插件不碰硬件、不写文件、不联网。设备通信由同目录的 bridge 程序负责。
 */

const HOST = "127.0.0.1";
const DEFAULT_PORT = 38333;
const STATE_VERSION = 1;

const sockets = new Set();
let unsubscribe = null;
let latest = null;
let lastKey = "";
let lastBroadcastAt = 0;

function num(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function str(value) {
  return value == null ? "" : String(value);
}

/* 歌词行在不同版本里可能是字符串或对象，这里统一成对象 */
function normalizeLine(line) {
  if (line == null) return { t: "", s: 0, e: 0, r: "" };
  if (typeof line === "string") return { t: line, s: 0, e: 0, r: "" };
  return {
    t: str(line.text ?? line.content ?? line.words ?? line.value),
    s: num(line.startTime ?? line.time ?? line.start ?? line.startMs, 0),
    e: num(line.endTime ?? line.end ?? line.endMs, 0),
    r: str(line.translation ?? line.trans ?? line.subText),
  };
}

/* 整个快照摊平成普通对象，避免把响应式对象 / 循环引用丢进 JSON.stringify */
function buildState(snapshot) {
  const snap = snapshot || {};
  const playback = snap.playback || {};
  const lyric = snap.lyric || {};
  const lines = Array.isArray(lyric.lines) ? lyric.lines : [];

  return {
    type: "state",
    ver: STATE_VERSION,
    title: str(playback.title),
    artist: str(playback.artist),
    album: str(playback.album),
    duration: num(playback.duration, 0),
    currentTime: num(playback.currentTime, 0),
    updatedAt: num(playback.updatedAt, Date.now()),
    playbackRate: num(playback.playbackRate, 1) || 1,
    isPlaying: !!playback.isPlaying,
    isPersonalFM: !!playback.isPersonalFM,
    accentColor: str(snap.appearance && snap.appearance.accentColor),
    lyricOffset: num(lyric.timeOffset, 0),
    lyricLoading: !!lyric.loading,
    currentIndex: Number.isInteger(lyric.currentIndex) ? lyric.currentIndex : -1,
    lines: lines.map(normalizeLine),
    serverTime: Date.now(),
  };
}

/* 判断"内容是否真的变了"，避免进度刷新导致的无意义推送 */
function signature(state) {
  return [
    state.title,
    state.artist,
    state.currentIndex,
    state.isPlaying ? 1 : 0,
    state.playbackRate,
    state.lines.length,
    state.lyricLoading ? 1 : 0,
  ].join("\u0001");
}

function push(state) {
  const payload = JSON.stringify(state);
  for (const socket of Array.from(sockets)) {
    try {
      socket.send(payload);
    } catch (err) {
      sockets.delete(socket);
    }
  }
}

function publish(snapshot) {
  latest = buildState(snapshot);
  const key = signature(latest);
  const now = Date.now();
  // 内容变化立即推；内容没变则最多 1 秒补一次进度基准，供对端本地推算
  if (key !== lastKey || now - lastBroadcastAt > 1000) {
    lastKey = key;
    lastBroadcastAt = now;
    push(latest);
  }
}

export async function activate(ctx) {
  let result;
  try {
    result = await ctx.webServer.listen({
      port: DEFAULT_PORT,
      maxConnections: 8,
      onRequest(request) {
        if (request.path === "/state") {
          return (
            latest || {
              type: "state",
              ver: STATE_VERSION,
              title: "",
              lines: [],
              currentIndex: -1,
              isPlaying: false,
            }
          );
        }
        if (request.path === "/ping") {
          return { ok: true, ver: STATE_VERSION, service: "halo-pixelbar-lyric" };
        }
        return {
          headers: { "content-type": "text/plain; charset=utf-8" },
          body: "HaloEchoLyric bridge endpoint. GET /state",
        };
      },
      onConnection(socket) {
        sockets.add(socket);
        if (latest) {
          try {
            socket.send(JSON.stringify(latest));
          } catch (err) {
            /* 忽略：对端可能已断开 */
          }
        }
        socket.onMessage(({ data }) => {
          if (data === "ping") {
            try {
              socket.send("pong");
            } catch (err) {
              /* 忽略 */
            }
          }
        });
        const drop = () => sockets.delete(socket);
        socket.onClose(drop);
        socket.onError(drop);
      },
    });
  } catch (err) {
    ctx.toast?.warning?.(`Halo PixelBar 歌词桥启动失败：${err && err.message ? err.message : err}`);
    return;
  }

  if (result && result.ok === false) {
    ctx.toast?.warning?.(`Halo PixelBar 歌词桥启动失败：${result.error || "端口被占用"}`);
    return;
  }

  try {
    publish(await ctx.nowPlaying.getSnapshot());
  } catch (err) {
    /* 快照还不可用时忽略，等 onSnapshot 推送 */
  }

  try {
    unsubscribe = ctx.nowPlaying.onSnapshot(publish);
  } catch (err) {
    ctx.toast?.warning?.("Halo PixelBar 歌词桥：无法订阅播放状态");
    return;
  }

  ctx.dispose(() => {
    try {
      unsubscribe?.();
    } catch (err) {
      /* 忽略 */
    }
    unsubscribe = null;
    sockets.clear();
  });

  const where = (result && (result.url || `${HOST}:${result.port}`)) || `${HOST}:${DEFAULT_PORT}`;
  ctx.toast?.success?.(`Halo PixelBar 歌词桥已就绪：${where}`);
}

export function deactivate(ctx) {
  try {
    unsubscribe?.();
  } catch (err) {
    /* 忽略 */
  }
  unsubscribe = null;
  sockets.clear();
  try {
    ctx.webServer.close();
  } catch (err) {
    /* 忽略 */
  }
}
