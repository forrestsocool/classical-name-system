// 每张卡片携带任务编号。预加载只追加队列，不改变当前卡片的收藏归属。
export function 初始化滑卡({读取接口, 转义, 会话密钥, 收藏夹编号, 显示状态}) {
  const $ = (选择) => document.querySelector(选择);
  const 内容 = $("#卡片内容");
  const 弹窗 = $("#条件弹窗");
  const 缓存键 = `起名滑卡v1:${会话密钥}`;
  const 同步键 = `起名待收藏v1:${会话密钥}`;
  const 偏好键 = "起名偏好v1";
  const 读缓存 = (键, 默认) => { try { return JSON.parse(localStorage.getItem(键)) ?? 默认; } catch { return 默认; } };
  const 写缓存 = (键, 数据) => { try { localStorage.setItem(键, JSON.stringify(数据)); } catch { /* 禁用存储时仍可浏览本次队列。 */ } };
  let 条件 = 读缓存(偏好键, null);
  const 合法条件 = (值) => 值 && /^[\u3400-\u4dbf\u4e00-\u9fff]{1,4}$/.test(值.姓氏) && [1, 2].includes(值.名字长度);
  if (!合法条件(条件)) 条件 = null;
  const 原缓存 = 读缓存(缓存键, {});
  let 队列 = [], 排除 = new Set(), 已看 = 0, 最近跳过 = null;
  let 版本 = 0, 加载中 = null, 错误信息 = "", 动画中 = false, 当前页 = "发现";
  let 已收藏 = 0, 收藏发送中 = false, 消息定时器;
  let 待收藏 = 读缓存(同步键, []);
  const 合法卡片 = (卡) => 卡 && typeof 卡.任务编号 === "string" && 卡.项目 && typeof 卡.项目.姓名 === "string" && typeof 卡.项目.名字 === "string";
  if (!Array.isArray(待收藏)) 待收藏 = [];
  待收藏 = 待收藏.filter(x => 合法卡片(x.卡));
  if (条件 && JSON.stringify(原缓存.条件) === JSON.stringify(条件) && Date.now() - 原缓存.时间 < 7 * 86400000) {
    队列 = Array.isArray(原缓存.队列) ? 原缓存.队列.filter(合法卡片).slice(0, 36) : [];
    排除 = new Set(Array.isArray(原缓存.排除) ? 原缓存.排除.slice(-5000) : []);
    已看 = Number(原缓存.已看) || 0;
    队列.forEach(卡 => 排除.add(卡.项目.姓名));
  }

  function 保存() {
    写缓存(缓存键, {条件, 队列, 排除: [...排除].slice(-5000), 已看, 时间: Date.now()});
  }
  function 通知(文字, 类型 = "成功") {
    clearTimeout(消息定时器);
    显示状态(文字, 类型);
    消息定时器 = setTimeout(() => 显示状态(""), 6500);
  }
  function 更新状态() {
    $("#姓氏摘要").textContent = 条件 ? `${条件.姓氏}姓 · ${条件.名字长度 === 2 ? "双字名" : "单字名"}` : "先告诉我你的姓氏";
    $("#浏览计数").textContent = 已看 ? `已遇见 ${已看} 个名字` : "从第一个名字开始";
    $("#跳过").disabled = $("#收藏").disabled = 动画中 || !队列.length;
    $("#撤回").disabled = 动画中 || !最近跳过;
    $("#重试预载").hidden = !错误信息;
    $("#重试预载").disabled = Boolean(加载中);
    const 秒数 = 加载中 ? Math.floor((Date.now() - 加载中.开始) / 1000) : 0;
    $("#预载状态").textContent = 错误信息
      ? `${队列.length ? "已备卡片仍可继续看。" : ""}${错误信息}`
      : 加载中 ? `${队列.length ? "下一组正在准备，可以继续滑动" : "正在细读古籍，为你挑选名字"} · ${秒数}秒`
      : 队列.length ? `已为你准备 ${队列.length} 个名字` : "为下一次相遇留一点期待";
    $("#预载状态").classList.toggle("准备中", Boolean(加载中));
    if (!队列.length) $("#空卡提示")?.replaceChildren(document.createTextNode(错误信息 || (条件 ? "第一组名字需要一点时间，准备好就会出现在这里。" : "告诉我们姓氏，开启一段名字之旅。")));
  }
  function 画卡() {
    更新状态();
    if (!队列.length) {
      内容.innerHTML = `<div class="等待卡 ${条件 && !错误信息 ? "呼吸" : ""}"><span class="卡片花纹" aria-hidden="true">✧</span><p class="眉题">${条件 ? "好名字，正在路上" : "从一个姓氏开始"}</p><h2>${条件 ? "一字一意<br>慢慢相遇" : "下一份心动<br>会是什么名字？"}</h2><div class="等待线" aria-hidden="true"></div><p id="空卡提示"></p>${!条件 ? '<button type="button" id="填写姓氏">填写姓氏，开始发现</button>' : ''}</div>`;
      $("#填写姓氏")?.addEventListener("click", 打开条件);
      更新状态();
      return;
    }
    const {项目: 项, 任务编号} = 队列[0];
    const 释义 = 项.现代释义 || 项.五行匹配?.现代释义 || "细读原文，感受这个名字的意境。";
    const 标签 = 项.文化标签 || 项.五行匹配?.文化标签 || [];
    const 出处状态 = 项.出处核验状态 || 项.五行匹配?.出处核验状态 || "待核验";
    const 原文 = 项.原文 || "";
    const 起点 = Math.max(0, (项.原文位置 || 0) - 24);
    const 摘录 = (起点 ? "…" : "") + 原文.slice(起点, 起点 + 95) + (原文.length > 起点 + 95 ? "…" : "");
    内容.innerHTML = `<article class="名字卡片 滑动卡" tabindex="0" aria-label="${转义(项.姓名)}，左滑跳过，右滑收藏" data-run="${转义(任务编号)}">
      <div class="滑动印章 跳过印章" aria-hidden="true">再相遇</div><div class="滑动印章 收藏印章" aria-hidden="true">心动收藏</div>
      <div class="卡片眉题"><span>一份来自古籍的心意</span><span class="小印章" aria-hidden="true">名</span></div>
      <div class="名字主区"><p class="拼音">${转义(项.拼音带调 || 项.拼音)}</p><div class="名字行 ${项.姓名.length > 4 ? "长姓名" : ""}"><h2>${转义(项.姓名)}</h2></div><div class="文化标签">${标签.slice(0, 4).map(x => `<span class="结果标签">${转义(x)}</span>`).join("")}</div></div>
      <p class="名字释义">${转义(释义)}</p>
      <div class="出处摘录"><span class="出处小题">名字的来处</span><blockquote>${转义(摘录)}</blockquote><p>${转义(项.书名)} · ${转义(项.篇章)}</p></div>
      <details class="卡片详情"><summary>细读典故与五行参考 <span aria-hidden="true">＋</span></summary><div class="详情正文"><blockquote>${转义(原文)}</blockquote><p>出处${转义(出处状态)} · ${转义(项.取字方式)}</p><p>五行参考：${转义(Object.entries(项.五行匹配?.已知字符 || {}).map(([字, 行]) => `${字}属${行}`).join("、") || "暂无已核验属性")}</p>${(项.五行匹配?.标签 || []).map(x => `<span class="结果标签">${转义(x)}</span>`).join("")}<small>${转义(项.五行匹配?.说明 || "五行仅作传统取名参考。")}</small></div></details>
    </article>`;
    $("#卡片播报").textContent = `${项.姓名}。${标签.join("，")}。`;
    绑定手势(内容.firstElementChild);
  }

  // 每个页面只保留一个生成请求；旧条件请求结束后才发新条件请求。
  async function 预取(手动 = false, 首批预热 = false) {
    if (!条件 || 加载中 || document.hidden || 当前页 !== "发现" || (!手动 && (错误信息 || 队列.length > 12))) return;
    const 本轮 = {版本, 开始: Date.now(), 首轮: !队列.length && 已看 === 0};
    加载中 = 本轮;
    错误信息 = "";
    const 当时已看 = 已看;
    const 请求 = {...条件, 随机种子: crypto.getRandomValues(new Uint32Array(1))[0] % 2147483647, 排除名字: [...排除].slice(-5000)};
    更新状态();
    try {
      const 数据 = await 读取接口("/api/name-runs", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(请求), signal: AbortSignal.timeout(180000)});
      if (本轮.版本 !== 版本) return;
      const 曾空 = !队列.length;
      let 加入 = 0;
      for (const 项目 of 数据.候选 || []) {
        const 卡 = {项目, 任务编号: 数据.任务编号};
        if (!合法卡片(卡) || 排除.has(项目.姓名) || !项目.姓名.startsWith(条件.姓氏)) continue;
        排除.add(项目.姓名);
        队列.push(卡);
        加入++;
      }
      if (!加入) 错误信息 = 数据.原因 || "这次没有找到更多合适的名字，可以再试一次。";
      保存();
      if (曾空 && !动画中) 画卡();
    } catch (错误) {
      if (本轮.版本 === 版本) 错误信息 = 错误.name === "TimeoutError" ? "准备时间较长，请稍后重试。" : (错误.message || "暂时没有连上服务，请稍后重试。");
    } finally {
      加载中 = null;
      更新状态();
      if (本轮.版本 !== 版本) { void 预取(false, true); }
      else if (!错误信息 && (首批预热 || 本轮.首轮 || 已看 > 当时已看)) { void 预取(); }
    }
  }

  function 更新同步状态() {
    写缓存(同步键, 待收藏);
    const 失败数 = 待收藏.filter(x => x.失败).length;
    $("#收藏同步提示").hidden = !待收藏.length;
    $("#同步文字").textContent = 失败数 ? `${失败数}个收藏暂未同步，已保存在本机。` : `正在保存 ${待收藏.length} 个心动名字…`;
    $("#重试收藏").hidden = !失败数;
    $("#重试收藏").disabled = 收藏发送中;
    $("#收藏计数").textContent = 已收藏 ? String(已收藏) : "";
  }
  async function 同步收藏() {
    if (收藏发送中) return;
    收藏发送中 = true;
    更新同步状态();
    try {
      for (const 项 of [...待收藏]) {
        if (项.失败) continue;
        try {
          await 读取接口("/api/favorites", {method: "POST", headers: {"Content-Type": "application/json"}, signal: AbortSignal.timeout(15000), body: JSON.stringify({collection_id: 收藏夹编号, run_id: 项.卡.任务编号, full_name: 项.卡.项目.姓名})});
          待收藏 = 待收藏.filter(x => x !== 项);
          已收藏++;
          通知(`已收藏「${项.卡.项目.姓名}」`);
          document.dispatchEvent(new CustomEvent("收藏已更新"));
        } catch { 项.失败 = true; }
        更新同步状态();
      }
    } finally {
      收藏发送中 = false;
      更新同步状态();
      // 滑动期间加入的新收藏也会继续发送。
      if (待收藏.some(x => !x.失败)) void 同步收藏();
    }
  }
  async function 选择(喜欢) {
    if (动画中 || !队列.length || 弹窗.open) return;
    const 卡 = 队列[0], 本版 = 版本;
    动画中 = true;
    更新状态();
    const 元素 = $(".滑动卡");
    if (元素) {
      元素.classList.add("离场", 喜欢 ? "向右离场" : "向左离场");
      元素.style.setProperty("--位移", `${(喜欢 ? 1 : -1) * 550}px`);
      元素.style.setProperty("--倾斜", `${喜欢 ? 16 : -16}deg`);
    }
    if (!matchMedia("(prefers-reduced-motion: reduce)").matches) await new Promise(resolve => setTimeout(resolve, 180));
    if (本版 !== 版本) { 动画中 = false; 画卡(); return; }
    队列.shift();
    已看++;
    最近跳过 = 喜欢 ? null : 卡;
    if (喜欢 && !待收藏.some(x => x.卡.项目.姓名 === 卡.项目.姓名)) 待收藏.push({卡, 失败: false});
    保存();
    动画中 = false;
    画卡();
    if (喜欢) void 同步收藏();
    void 预取();
  }
  function 绑定手势(元素) {
    let 手势 = null;
    const 复原 = () => {
      手势 = null;
      元素.classList.remove("拖动中");
      for (const 键 of ["--位移", "--倾斜", "--收藏透明度", "--跳过透明度"]) 元素.style.removeProperty(键);
    };
    元素.addEventListener("pointerdown", 事件 => {
      if (事件.button !== 0 || 动画中 || 事件.target.closest("summary, details, a, button")) return;
      手势 = {id: 事件.pointerId, x: 事件.clientX, y: 事件.clientY, dx: 0, dy: 0};
      元素.setPointerCapture(事件.pointerId);
    });
    元素.addEventListener("pointermove", 事件 => {
      if (!手势 || 手势.id !== 事件.pointerId) return;
      手势.dx = 事件.clientX - 手势.x;
      手势.dy = 事件.clientY - 手势.y;
      if (Math.abs(手势.dy) > Math.abs(手势.dx) && Math.abs(手势.dy) > 12) { 复原(); return; }
      元素.classList.add("拖动中");
      元素.style.setProperty("--位移", `${手势.dx}px`);
      元素.style.setProperty("--倾斜", `${手势.dx / 25}deg`);
      元素.style.setProperty("--收藏透明度", String(Math.max(0, 手势.dx / 110)));
      元素.style.setProperty("--跳过透明度", String(Math.max(0, -手势.dx / 110)));
    });
    元素.addEventListener("pointerup", 事件 => {
      if (!手势 || 手势.id !== 事件.pointerId) return;
      const 偏移 = 手势.dx;
      const 达标 = Math.abs(偏移) > Math.min(110, 元素.clientWidth * .25) && Math.abs(偏移) > Math.abs(手势.dy) * 1.2;
      if (元素.hasPointerCapture(事件.pointerId)) 元素.releasePointerCapture(事件.pointerId);
      if (达标) { 手势 = null; void 选择(偏移 > 0); } else 复原();
    });
    元素.addEventListener("pointercancel", 复原);
  }
  function 打开条件() {
    if (条件) for (const 键 of ["姓氏", "名字长度", "必须包含", "避用字"]) $(`#${键}`).value = 条件[键] ?? "";
    $("#条件错误").textContent = "";
    弹窗.showModal();
  }
  $("#编辑条件").addEventListener("click", 打开条件);
  $("#关闭条件").addEventListener("click", () => 弹窗.close());
  $("#起名表单").addEventListener("submit", 事件 => {
    事件.preventDefault();
    const 新条件 = {姓氏: $("#姓氏").value.trim(), 名字长度: Number($("#名字长度").value), 必须包含: $("#必须包含").value.trim(), 避用字: $("#避用字").value.trim()};
    if (!合法条件(新条件) || 新条件.必须包含.length > 新条件.名字长度 || [...新条件.必须包含].some(x => 新条件.避用字.includes(x))) {
      $("#条件错误").textContent = "请填写一至四个汉字的姓氏，固定字不能超过名字字数，也不能与避用字冲突。";
      return;
    }
    弹窗.close();
    if (JSON.stringify(新条件) === JSON.stringify(条件)) { 显示发现(); return; }
    条件 = 新条件;
    写缓存(偏好键, 条件);
    版本++;
    队列 = []; 排除 = new Set(); 已看 = 0; 最近跳过 = null; 错误信息 = "";
    保存();
    显示发现();
    画卡();
    void 预取(false, true);
  });
  function 显示发现() { document.querySelector('[data-page="发现"]').click(); }
  $("#跳过").addEventListener("click", () => 选择(false));
  $("#收藏").addEventListener("click", () => 选择(true));
  $("#撤回").addEventListener("click", () => {
    if (!最近跳过 || 动画中) return;
    队列.unshift(最近跳过); 最近跳过 = null; 已看 = Math.max(0, 已看 - 1); 保存(); 画卡();
  });
  $("#重试预载").addEventListener("click", () => 预取(true));
  $("#重试收藏").addEventListener("click", () => { 待收藏.forEach(x => x.失败 = false); void 同步收藏(); });
  document.addEventListener("keydown", 事件 => {
    if (当前页 !== "发现" || 弹窗.open || 事件.repeat || 事件.target.closest("input,select,textarea,details,[contenteditable]")) return;
    if (["ArrowLeft", "ArrowRight"].includes(事件.key)) { 事件.preventDefault(); void 选择(事件.key === "ArrowRight"); }
  });
  document.querySelectorAll("[data-page]").forEach(按钮 => 按钮.addEventListener("click", () => {
    当前页 = 按钮.dataset.page;
    for (const 名 of ["发现", "收藏", "更多"]) $(`#${名}页`).hidden = 名 !== 当前页;
    document.querySelectorAll("[data-page]").forEach(x => { x.classList.toggle("选中", x === 按钮); if (x === 按钮) x.setAttribute("aria-current", "page"); else x.removeAttribute("aria-current"); });
    if (当前页 === "发现") void 预取();
    if (当前页 === "收藏") document.dispatchEvent(new CustomEvent("打开收藏"));
  }));
  document.addEventListener("visibilitychange", () => { if (!document.hidden) void 预取(); });
  window.addEventListener("online", () => { 待收藏.forEach(x => x.失败 = false); void 同步收藏(); if (错误信息) void 预取(true); });
  document.addEventListener("收藏数量更新", 事件 => { 已收藏 = 事件.detail; 更新同步状态(); });
  // 刷新恢复时将未确认的收藏重新同步，服务端按姓名幂等处理。
  待收藏.forEach(x => x.失败 = false);
  画卡(); 更新同步状态();
  setInterval(() => { if (加载中 && !document.hidden) 更新状态(); }, 1000);
  if (条件) void 预取(false, !队列.length);
  else 打开条件();
  void 同步收藏();
}
