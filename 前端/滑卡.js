// 有效租约预加载，实际露出才确认曝光。指纹仅标识设备，不替代会话认证。
export async function 初始化滑卡({读取接口, 转义, 会话密钥, 收藏夹编号, 显示状态}) {
  const $ = x => document.querySelector(x);
  const 读 = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
  const 写 = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };
  const 读页 = (k, d) => { try { return JSON.parse(sessionStorage.getItem(k)) ?? d; } catch { return d; } };
  const 数组 = x => Array.isArray(x) ? x : [];
  let 指纹 = 读("起名设备指纹v1", "");
  if (!/^[a-f0-9]{64}$/.test(指纹)) {
    // 带安装盐的粗粒度指纹，不采集画布、字体清单，不跨站追踪。
    const 特征 = [会话密钥, navigator.language, navigator.platform, navigator.maxTouchPoints, Intl.DateTimeFormat().resolvedOptions().timeZone];
    指纹 = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(特征))))].map(x => x.toString(16).padStart(2, "0")).join("");
    写("起名设备指纹v1", 指纹);
  }
  const 缓存键 = `起名滑卡v2:${会话密钥}`, 同步键 = `起名待收藏v1:${会话密钥}`, 曝光键 = `起名待曝光v1:${会话密钥}`;
  const 内容 = $("#卡片内容"), 弹窗 = $("#条件弹窗"), 详情 = $("#名字详情");
  const 合法条件 = x => x && /^[\u3400-\u4dbf\u4e00-\u9fff]{1,4}$/.test(x.姓氏) && [1, 2].includes(x.名字长度);
  let 条件 = 读("起名偏好v1", null);
  if (!合法条件(条件)) 条件 = null;
  let 队列 = [], 池号 = null, 已看 = 0, 最近跳过 = null, 当前页 = "发现", 版本 = 0;
  let 请求中 = null, 请求编号 = null, 下次拉取 = 0, 错误信息 = "", 提示 = "正在从不同古籍挑选名字";
  let 待收藏 = 读(同步键, []), 待曝光 = new Set(数组(读(曝光键, []))), 同步中 = false, 收藏发送中 = false, 已收藏 = 0;
  let 已展示 = new Set(), 曝光定时器, 连续失败 = 0;
  const 合法卡 = x => x?.项目?.姓名 && typeof x.任务编号 === "string";
  待收藏 = Array.isArray(待收藏) ? 待收藏.filter(x => 合法卡(x.卡)) : [];
  const 缓存 = 读页(缓存键, {});
  if (条件 && JSON.stringify(缓存.条件) === JSON.stringify(条件)) {
    队列 = 数组(缓存.队列).filter(x => 合法卡(x) && x.到期时间 > Date.now()).slice(0, 24);
    已展示 = new Set(数组(缓存.已展示)); 池号 = 缓存.池号 || null; 已看 = Number(缓存.已看) || 0;
  }
  const 活跃 = () => !document.hidden && 当前页 === "发现";
  const 带租约 = () => 队列.filter(x => !已展示.has(x.投递编号)).map(x => x.投递编号);
  function 保存() {
    try { sessionStorage.setItem(缓存键, JSON.stringify({条件, 队列, 池号, 已看, 已展示: 队列.filter(x => 已展示.has(x.投递编号)).map(x => x.投递编号)})); } catch {}
    写(曝光键, [...待曝光]);
  }
  function 更新状态() {
    $("#姓氏摘要").textContent = 条件 ? `${条件.姓氏}姓${条件.必须包含 ? ` · 含${条件.必须包含}` : ""} · ${条件.名字长度 === 2 ? "双字" : "单字"}` : "填写姓氏";
    $("#浏览计数").textContent = 已看 ? `已遇见 ${已看} 个` : "一字一意，慢慢相遇";
    $("#跳过").disabled = $("#收藏").disabled = !队列.length;
    $("#撤回").disabled = !最近跳过;
    $("#重试预载").hidden = !错误信息;
    $("#预载状态").textContent = 队列.length ? `${队列.length} 个名字已备好${错误信息 ? " · 正在重连" : " · 左滑跳过，右滑收藏"}` : (错误信息 || 提示);
    $("#预载状态").classList.toggle("准备中", !队列.length && !!条件);
  }
  async function 同步曝光(释放 = []) {
    if (同步中 && !释放.length) return;
    const 这次 = [...待曝光].slice(0, 48), 续租 = 活跃() ? 带租约() : [];
    同步中 = true;
    try {
      const 数据 = await 读取接口("/api/feed/sync", {method: "POST", headers: {"Content-Type": "application/json"}, signal: AbortSignal.timeout(10000), body: JSON.stringify({指纹, 队列编号: 活跃() ? 池号 : null, 已展示: 这次, 续租, 释放})});
      这次.forEach(x => 待曝光.delete(x));
      const 有效 = new Set(数据.有效租约 || 续租);
      队列 = 队列.filter(x => 已展示.has(x.投递编号) || !续租.includes(x.投递编号) || 有效.has(x.投递编号));
      队列.forEach(x => { if (有效.has(x.投递编号)) x.到期时间 = Date.now() + 295000; }); 保存();
    } catch { /* 离线确认保留到下次重试；未确认租约仍防止重复投递。 */ }
    finally { 同步中 = false; }
  }
  function 记曝光(卡) {
    if (!活跃() || 弹窗.open || 详情.open || !卡 || 已展示.has(卡.投递编号)) return;
    已展示.add(卡.投递编号); 待曝光.add(卡.投递编号); 保存();
    if (!曝光定时器) 曝光定时器 = setTimeout(() => { 曝光定时器 = null; void 同步曝光(); }, 1500);
  }
  function 卡片HTML(卡, 背面 = false) {
    const 项 = 卡.项目, 标签 = 项.文化标签 || 项.五行匹配?.文化标签 || [];
    const 原文 = 项.原文 || "", 起点 = Math.max(0, (项.原文位置 || 0)-20);
    const 摘录 = (起点 ? "…" : "") + 原文.slice(起点, 起点+90) + (原文.length > 起点+90 ? "…" : "");
    return `<article class="名字卡片 ${背面 ? "下一张" : "滑动卡"}" ${背面 ? 'aria-hidden="true" inert' : `tabindex="0" aria-label="${转义(项.姓名)}，左滑跳过，右滑收藏"`} data-run="${转义(卡.任务编号)}">
      <div class="滑动印章 跳过印章" aria-hidden="true">跳过</div><div class="滑动印章 收藏印章" aria-hidden="true">心动</div>
      <div class="卡片眉题"><span>${转义(项.书名)}</span><span class="小印章" aria-hidden="true">名</span></div>
      <div class="名字主区"><p class="拼音">${转义(项.拼音带调 || 项.拼音)}</p><div class="名字行 ${项.姓名.length > 4 ? "长姓名" : ""}"><h2>${转义(项.姓名)}</h2></div><div class="文化标签">${标签.slice(0, 3).map(x => `<span class="结果标签">${转义(x)}</span>`).join("")}</div></div>
      <p class="名字释义">${转义(项.现代释义 || 项.五行匹配?.现代释义 || "细读原文，感受名字的意境。")}</p>
      <div class="出处摘录"><blockquote>${转义(摘录)}</blockquote><p>${转义(项.书名)} · ${转义(项.篇章)}</p></div>
      <button class="打开详情" type="button" ${背面 ? 'tabindex="-1"' : ""}>典故、热度与五行参考 <span aria-hidden="true">↗</span></button>
    </article>`;
  }
  function 画卡() {
    更新状态();
    // 离场层独立存在；下一张即刻可操作，不等待动画或网络。
    内容.querySelectorAll(":scope > :not(.离场)").forEach(x => x.remove());
    if (!队列.length) {
      内容.insertAdjacentHTML("beforeend", `<div class="等待卡"><span class="卡片花纹" aria-hidden="true">✧</span><p class="眉题">${条件 ? "好名字，正在路上" : "从一个姓氏开始"}</p><h2>一字一意<br>慢慢相遇</h2><p>${条件 ? "正在细读不同古籍，合适的名字会陆续出现" : "填写一次姓氏，下次直接继续"}</p>${!条件 ? '<button id="填写姓氏" type="button">填写姓氏</button>' : ""}</div>`);
      $("#填写姓氏")?.addEventListener("click", 打开条件); return;
    }
    if (队列[1]) 内容.insertAdjacentHTML("beforeend", 卡片HTML(队列[1], true));
    内容.insertAdjacentHTML("beforeend", 卡片HTML(队列[0]));
    const 卡 = 队列[0], 元素 = 内容.querySelector(".滑动卡:not(.离场)");
    元素.querySelector(".打开详情").addEventListener("click", () => 打开详情(卡));
    $("#卡片播报").textContent = `${卡.项目.姓名}，出自${卡.项目.书名}`;
    绑定手势(元素, 卡); 记曝光(卡);
  }
  function 打开详情(卡) {
    const 项 = 卡.项目, 行 = 项.五行匹配 || {}, 热 = 项.热门提示 || 行.热门提示;
    $("#详情内容").innerHTML = `<p class="眉题">${转义(项.书名)} · ${转义(项.篇章)}</p><h2>${转义(项.姓名)}</h2><p>${转义(项.现代释义 || 行.现代释义)}</p><blockquote>${转义(项.原文)}</blockquote><p>出处${转义(项.出处核验状态 || 行.出处核验状态 || "待核验")} · ${转义(项.取字方式)}</p><details class="热门详情"><summary>热门提醒${热?.命中 ? " · 有命中" : " · 未命中已收录榜单"}</summary><ul>${(热?.提示 || []).map(x => `<li>${转义(x)}</li>`).join("")}</ul><small>仅匹配已收录的公安部姓名报告，不代表实时重名率。</small></details><details><summary>五行参考</summary><p>${转义(Object.entries(行.已知字符 || {}).map(([字, 五行]) => `${字}属${五行}`).join("、") || "暂无已核验属性")}</p>${(行.标签 || []).map(x => `<span class="结果标签">${转义(x)}</span>`).join("")}<p>${转义(行.说明 || "五行仅作传统取名参考。")}</p></details>`;
    详情.showModal();
  }
  async function 预取(强制 = false) {
    if (!条件 || 请求中 || !活跃() || (!强制 && (队列.length >= 16 || Date.now() < 下次拉取))) return;
    const 控制器 = new AbortController(), 本版 = 版本; 请求中 = 控制器; 请求编号 ||= crypto.randomUUID();
    const 编号 = 请求编号, 超时 = setTimeout(() => 控制器.abort(), 12000);
    try {
      const 数据 = await 读取接口("/api/feed/pull", {method: "POST", headers: {"Content-Type": "application/json"}, signal: 控制器.signal, body: JSON.stringify({指纹, 请求编号: 编号, 条件, 数量: 8})});
      if (本版 !== 版本) return;
      请求编号 = null; 连续失败 = 0; 错误信息 = ""; 池号 = 数据.队列编号; 提示 = 数据.提示 || "正在准备更多来源";
      const 曾空 = !队列.length, 已有 = new Set(队列.map(x => x.项目.姓名));
      for (const 卡 of 数据.卡片 || []) {
        if (合法卡(卡) && 卡.投递编号 && !已有.has(卡.项目.姓名) && !已展示.has(卡.投递编号) && 卡.项目.姓名.startsWith(条件.姓氏)) { 已有.add(卡.项目.姓名); 队列.push(卡); }
      }
      下次拉取 = Date.now() + (数据.卡片?.length ? 1000 : Math.max(3, 数据.重试秒数 || 4)*1000);
      保存(); if (曾空) 画卡();
    } catch (e) {
      if (本版 === 版本) { 错误信息 = "连接稍慢，正在自动重试"; 下次拉取 = Date.now() + Math.min(30000, 3000 * 2 ** 连续失败++); }
    } finally { clearTimeout(超时); if (请求中 === 控制器) 请求中 = null; 更新状态(); }
  }
  function 更新同步状态() {
    写(同步键, 待收藏);
    const 失败数 = 待收藏.filter(x => x.失败).length;
    $("#收藏同步提示").hidden = !失败数; $("#同步文字").textContent = `${失败数} 个收藏已保存在本机，等待同步`;
    $("#重试收藏").disabled = 收藏发送中; $("#收藏计数").textContent = 已收藏 ? String(已收藏) : "";
  }
  async function 同步收藏() {
    if (收藏发送中) return; 收藏发送中 = true;
    try {
      for (const 项 of [...待收藏]) {
        if (项.失败) continue;
        try {
          await 读取接口("/api/favorites", {method: "POST", headers: {"Content-Type": "application/json"}, signal: AbortSignal.timeout(15000), body: JSON.stringify({collection_id: 收藏夹编号, run_id: 项.卡.任务编号, full_name: 项.卡.项目.姓名})});
          待收藏 = 待收藏.filter(x => x !== 项); 已收藏++; document.dispatchEvent(new CustomEvent("收藏已更新"));
        } catch { 项.失败 = true; }
        更新同步状态();
      }
    } finally { 收藏发送中 = false; 更新同步状态(); if (待收藏.some(x => !x.失败)) void 同步收藏(); }
  }
  function 选择(喜欢, 期望卡 = 队列[0]) {
    if (!队列.length || 队列[0] !== 期望卡 || 弹窗.open || 详情.open) return;
    const 卡 = 队列.shift(), 元素 = 内容.querySelector(".滑动卡:not(.离场)");
    if (元素) {
      元素.classList.remove("拖动中"); 元素.classList.add("离场", 喜欢 ? "向右离场" : "向左离场"); 元素.inert = true; 元素.setAttribute("aria-hidden", "true");
      requestAnimationFrame(() => { 元素.style.setProperty("--位移", `${(喜欢 ? 1 : -1) * (innerWidth + 400)}px`); 元素.style.setProperty("--倾斜", `${喜欢 ? 22 : -22}deg`); });
      setTimeout(() => 元素.remove(), 300);
    }
    已看++; 最近跳过 = 喜欢 ? null : 卡;
    if (喜欢 && !待收藏.some(x => x.卡.项目.姓名 === 卡.项目.姓名)) 待收藏.push({卡, 失败: false});
    保存(); 画卡(); if (喜欢) void 同步收藏(); void 预取();
  }
  function 绑定手势(元素, 卡) {
    let 手势 = null, 帧 = 0;
    function 复原() {
      const id = 手势?.id; 手势 = null; cancelAnimationFrame(帧); 帧 = 0;
      if (id != null && 元素.hasPointerCapture(id)) 元素.releasePointerCapture(id);
      元素.classList.remove("拖动中"); ["--位移", "--倾斜", "--收藏透明度", "--跳过透明度"].forEach(x => 元素.style.removeProperty(x));
    }
    元素.addEventListener("pointerdown", e => {
      if (!e.isPrimary) { 复原(); return; }
      if (e.button !== 0 || e.target.closest("button,a") || 元素.classList.contains("离场")) return;
      手势 = {id: e.pointerId, x: e.clientX, y: e.clientY, dx: 0, dy: 0, lastX: e.clientX, lastT: performance.now(), v: 0}; 元素.setPointerCapture(e.pointerId);
    });
    元素.addEventListener("pointermove", e => {
      if (!手势 || e.pointerId !== 手势.id) return;
      const t = performance.now(); 手势.v = (e.clientX-手势.lastX)/Math.max(1, t-手势.lastT); 手势.lastX = e.clientX; 手势.lastT = t;
      手势.dx = e.clientX-手势.x; 手势.dy = e.clientY-手势.y;
      if (!帧) 帧 = requestAnimationFrame(() => {
        帧 = 0; if (!手势) return; 元素.classList.add("拖动中");
        元素.style.setProperty("--位移", `${手势.dx}px`); 元素.style.setProperty("--倾斜", `${手势.dx/28}deg`);
        元素.style.setProperty("--收藏透明度", String(Math.max(0, 手势.dx/95))); 元素.style.setProperty("--跳过透明度", String(Math.max(0, -手势.dx/95)));
      });
    });
    元素.addEventListener("pointerup", e => {
      if (!手势 || 手势.id !== e.pointerId) return;
      const {dx, dy, v, lastT} = 手势;
      const 足够 = Math.abs(dx) >= Math.min(90, 元素.clientWidth*.23) || (Math.abs(dx) > 28 && Math.abs(v) > .6 && performance.now()-lastT < 100);
      if (足够 && Math.abs(dx) > Math.abs(dy)*.85) {
        手势 = null; cancelAnimationFrame(帧); 帧 = 0; if (元素.hasPointerCapture(e.pointerId)) 元素.releasePointerCapture(e.pointerId); 选择(dx > 0, 卡);
      } else 复原();
    });
    元素.addEventListener("pointercancel", 复原); 元素.addEventListener("lostpointercapture", () => { if (手势) 复原(); }); 元素.addEventListener("dragstart", e => e.preventDefault());
  }
  function 打开条件() {
    if (条件) ["姓氏", "名字长度", "必须包含", "避用字"].forEach(k => $(`#${k}`).value = 条件[k] ?? "");
    $("#条件错误").textContent = ""; 弹窗.showModal();
  }
  $("#编辑条件").addEventListener("click", 打开条件); $("#关闭条件").addEventListener("click", () => 弹窗.close()); $("#关闭详情").addEventListener("click", () => 详情.close());
  for (const 窗 of [弹窗, 详情]) 窗.addEventListener("close", () => 记曝光(队列[0]));
  for (const 窗 of [弹窗, 详情]) 窗.addEventListener("click", e => { if (e.target === 窗) { const r = 窗.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) 窗.close(); } });
  $("#起名表单").addEventListener("submit", e => {
    e.preventDefault();
    const 新 = {姓氏: $("#姓氏").value.trim(), 名字长度: Number($("#名字长度").value), 必须包含: $("#必须包含").value.trim(), 避用字: $("#避用字").value.trim()};
    if (!合法条件(新) || (新.必须包含 && !/^[\u3400-\u4dbf\u4e00-\u9fff]+$/.test(新.必须包含)) || 新.必须包含.length > 新.名字长度 || [...新.必须包含].some(x => 新.避用字.includes(x))) { $("#条件错误").textContent = "请填写汉字姓氏；固定字不能超过名字字数，也不能与避用字冲突。"; return; }
    弹窗.close();
    if (JSON.stringify(新) !== JSON.stringify(条件)) {
      void 同步曝光(带租约()); 请求中?.abort(); 请求中 = null; 请求编号 = null; 版本++;
      条件 = 新; 写("起名偏好v1", 条件); 队列 = []; 池号 = null; 最近跳过 = null; 已看 = 0; 错误信息 = ""; 下次拉取 = 0; 已展示 = new Set();
      内容.replaceChildren(); 保存(); 画卡();
    }
    document.querySelector('[data-page="发现"]').click(); void 预取(true);
  });
  $("#跳过").addEventListener("click", () => 选择(false)); $("#收藏").addEventListener("click", () => 选择(true));
  $("#撤回").addEventListener("click", () => { if (!最近跳过 || 详情.open) return; 队列.unshift(最近跳过); 最近跳过 = null; 已看 = Math.max(0, 已看-1); 保存(); 画卡(); });
  $("#重试预载").addEventListener("click", () => { 下次拉取 = 0; void 预取(true); });
  $("#重试收藏").addEventListener("click", () => { 待收藏.forEach(x => x.失败 = false); void 同步收藏(); });
  document.addEventListener("keydown", e => {
    if (!活跃() || 弹窗.open || 详情.open || e.repeat || e.target.closest("input,select,textarea,details,[contenteditable]")) return;
    if (["ArrowLeft", "ArrowRight"].includes(e.key)) { e.preventDefault(); 选择(e.key === "ArrowRight"); }
  });
  document.querySelectorAll("[data-page]").forEach(b => b.addEventListener("click", () => {
    当前页 = b.dataset.page; ["发现", "收藏", "更多"].forEach(x => $(`#${x}页`).hidden = x !== 当前页);
    document.querySelectorAll("[data-page]").forEach(x => { x.classList.toggle("选中", x === b); if (x === b) x.setAttribute("aria-current", "page"); else x.removeAttribute("aria-current"); });
    if (当前页 === "发现") { 记曝光(队列[0]); void 预取(); } if (当前页 === "收藏") document.dispatchEvent(new CustomEvent("打开收藏"));
  }));
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { 队列 = 队列.filter(x => 已展示.has(x.投递编号) || x.到期时间 > Date.now()); 画卡(); void 同步曝光(); void 预取(); }
    else { 保存(); void 同步曝光(); }
  });
  window.addEventListener("online", () => { 待收藏.forEach(x => x.失败 = false); void 同步收藏(); void 同步曝光(); void 预取(true); });
  document.addEventListener("收藏数量更新", e => { 已收藏 = e.detail; 更新同步状态(); });
  待收藏.forEach(x => x.失败 = false);
  setInterval(() => { if (活跃()) { void 预取(); 更新状态(); } }, 1000);
  setInterval(() => { if (活跃()) void 同步曝光(); }, 20000);
  画卡(); 更新同步状态(); void 同步收藏(); if (条件) void 预取(); else 打开条件();
}
