(async () => {
const 方向列表 = document.querySelector("#方向列表");
const 起名表单 = document.querySelector("#起名表单");
const 状态 = document.querySelector("#状态");
const 八字结果 = document.querySelector("#八字结果");
const 结果列表 = document.querySelector("#结果列表");
const 换一批按钮 = document.querySelector("#换一批");
const 管理密钥 = document.querySelector("#管理密钥");
const 复核人 = document.querySelector("#复核人");
const 复核列表 = document.querySelector("#复核列表");
const 质量统计 = document.querySelector("#质量统计");
const 加载复核按钮 = document.querySelector("#加载复核");
const 加载五行规则按钮 = document.querySelector("#加载五行规则");
const 加载审计问题按钮 = document.querySelector("#加载审计问题");
const 加载统计按钮 = document.querySelector("#加载统计");
const 五行规则列表 = document.querySelector("#五行规则列表");
const 审计问题列表 = document.querySelector("#审计问题列表");
const 加载历史按钮 = document.querySelector("#加载历史");
const 历史列表 = document.querySelector("#历史列表");
const 年号关键词 = document.querySelector("#年号关键词");
const 年号地区 = document.querySelector("#年号地区");
const 加载年号按钮 = document.querySelector("#加载年号");
const 年号列表 = document.querySelector("#年号列表");
let 当前任务编号 = "";
let 最近请求 = null;
let 已展示名字 = [];
const 会话密钥 = (() => {
  const 旧编号 = localStorage.getItem("起名收藏夹");
  if (旧编号) return 旧编号;
  const 新编号 = `web-${crypto.randomUUID().replaceAll("-", "")}`;
  localStorage.setItem("起名收藏夹", 新编号);
  return 新编号;
})();
const 收藏夹编号 = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(会话密钥)))].map(字节 => 字节.toString(16).padStart(2, "0")).join("");

async function 会话请求(地址, 选项 = {}) {
  const 请求头 = new Headers(选项.headers);
  请求头.set("X-Session-Key", 会话密钥);
  return fetch(地址, {...选项, headers: 请求头});
}

function 显示状态(文字, 类型 = "") {
  状态.textContent = 文字;
  状态.className = `状态 ${类型}`;
}

function 转义(文字) {
  return String(文字 ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function 读取接口(地址, 选项 = {}) {
  const 响应 = await 会话请求(地址, 选项);
  const 数据 = await 响应.json();
  if (!响应.ok) {
    const 消息 = Array.isArray(数据.detail) ? 数据.detail.map(项 => 项.msg).join("；") : 数据.detail;
    throw new Error(消息 || "请求失败，请稍后重试");
  }
  return 数据;
}

document.querySelector("#模型补充").addEventListener("click", async (事件) => {
  const 编号 = 当前任务编号;
  const 按钮 = 事件.currentTarget;
  const 容器 = document.querySelector("#模型结果");
  按钮.disabled = true;
  容器.textContent = "正在校验出处并补充释义……";
  try {
    const 数据 = await 读取接口(`/api/name-runs/${encodeURIComponent(编号)}/model-candidates`, {method: "POST"});
    if (编号 !== 当前任务编号) return;
    容器.innerHTML = 数据.候选.map(项 => `<article><h3>${转义(项.名字)}</h3><p>${转义(项.现代释义)}</p><small>${转义(项.取字方式)} · ${转义((项.风险提示 || []).join("；"))}</small></article>`).join("") || "没有通过出处与用字校验的补充结果。";
  } catch (错误) {
    if (编号 === 当前任务编号) 容器.textContent = 错误.message;
  } finally {
    if (编号 === 当前任务编号) 按钮.disabled = false;
  }
});

async function 读取收藏() {
  const 数据 = await 读取接口(`/api/favorites?collection_id=${encodeURIComponent(收藏夹编号)}`);
  document.querySelector("#收藏列表").innerHTML = 数据.结果.map(项 => `<article><label><input type="checkbox" name="比较选项" value="${项.id}">${转义(项.full_name)}</label><p>${转义(项.book)} · ${转义(项.section_title)}</p><button type="button" data-delete-favorite="${项.id}">取消收藏</button></article>`).join("") || "还没有收藏名字。";
}
document.querySelector("#加载收藏").addEventListener("click", () => 读取收藏().catch(错误 => 显示状态(错误.message, "错误")));
document.querySelector("#收藏列表").addEventListener("click", async (事件) => {
  const 编号 = 事件.target.dataset.deleteFavorite;
  if (!编号) return;
  try {
    await 读取接口(`/api/favorites/${编号}?collection_id=${encodeURIComponent(收藏夹编号)}`, {method: "DELETE"});
    await 读取收藏();
  } catch (错误) { 显示状态(错误.message, "错误"); }
});
document.querySelector("#比较收藏").addEventListener("click", async () => {
  const 编号 = [...document.querySelectorAll('input[name="比较选项"]:checked')].map(项 => Number(项.value));
  if (!编号.length || 编号.length > 5) { 显示状态("请选择一至五个收藏名字", "提示"); return; }
  try {
    const 数据 = await 读取接口("/api/favorites/compare", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({collection_id: 收藏夹编号, favorite_ids: 编号})});
    document.querySelector("#比较结果").innerHTML = 数据.结果.map(项 => `<article><h3>${转义(项.full_name)}</h3><p>${转义(项.pinyin_tone)} · ${转义(项.direction)}</p><blockquote>${转义(项.source_text)}</blockquote><small>${转义(项.book)} · ${转义(项.section_title)}</small></article>`).join("");
  } catch (错误) { 显示状态(错误.message, "错误"); }
});

async function 读取方向() {
  const 响应 = await 会话请求("/api/directions");
  const 数据 = await 响应.json();
  方向列表.innerHTML = 数据.方向.map((项目, 索引) => `
    <label class="方向项">
      <input type="checkbox" name="方向" value="${转义(项目.名称)}" ${索引 === 0 ? "checked" : ""}>
      <span>${转义(项目.名称)}</span>
    </label>
  `).join("");
}

function 显示八字(八字) {
  if (!八字) {
    八字结果.innerHTML = "";
    return;
  }
  const 五行 = 八字.五行统计.明干支;
  八字结果.innerHTML = `
    <div class="八字卡片">
      <span>八字辅助</span>
      <strong>${八字.四柱.map(转义).join("　")}</strong>
      <small>明干支五行：${Object.entries(五行).map(([键, 值]) => `${键}${值}`).join("　")}　规则：${转义(八字.规则版本)}</small>
    </div>
  `;
}

function 显示候选(候选) {
  换一批按钮.hidden = !候选.length;
  if (!候选.length) {
    结果列表.innerHTML = "<div class=空结果>当前条件下没有候选，请减少限制后重试。</div>";
    return;
  }
  结果列表.innerHTML = 候选.map((项目) => `
    <article class="名字卡片">
      <div class="名字行"><h2>${转义(项目.姓名)}</h2><span>${转义(项目.方向)}</span></div>
      <p class="词组">${转义(项目.名字)}　<span class="拼音">${转义(项目.拼音带调 || 项目.拼音)}</span></p>
      <p>${转义(项目.书名)} · ${转义(项目.篇章)} · ${转义(项目.取字方式)}</p>
      <blockquote>${转义(项目.原文)}</blockquote>
      <small>五行参考：${转义(Object.entries(项目.五行匹配?.已知字符 || {}).map(([字, 行]) => `${字}属${行}`).join("、") || "暂无已核验属性")}</small>
      <details><summary>查看出处位置</summary><small>片段编号：${转义(项目.来源片段编号)}　原文位置：${转义(项目.原文位置)}</small></details>
      <button class="收藏按钮" data-name="${转义(项目.姓名)}">收藏这个名字</button>
      <div class="反馈操作" data-name="${转义(项目.姓名)}">
        <button class="反馈按钮" data-feedback="喜欢">喜欢</button>
        <button class="反馈按钮" data-feedback="不喜欢">不喜欢</button>
        <button class="反馈按钮" data-feedback="出处有误">出处有误</button>
        <button class="反馈按钮" data-feedback="读音不佳">读音不佳</button>
        <button class="反馈按钮" data-feedback="含义不符">含义不符</button>
      </div>
    </article>
  `).join("");
}

async function 执行起名(请求) {
  const 提交按钮 = 起名表单.querySelector('button[type="submit"]');
  if (提交按钮.disabled) return;
  提交按钮.disabled = true;
  换一批按钮.disabled = true;
  document.querySelector("#模型补充").disabled = true;
  document.querySelector("#模型结果").textContent = "";
  显示状态("正在生成……");
  结果列表.innerHTML = "";
  八字结果.innerHTML = "";
  try {
    const 响应 = await 会话请求("/api/name-runs", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(请求),
    });
    const 数据 = await 响应.json();
    if (!响应.ok) throw new Error(数据.detail || "请求失败");
    显示状态(`${数据.状态}　任务：${数据.任务编号}`, 数据.状态 === "完成" ? "成功" : "提示");
    当前任务编号 = 数据.任务编号;
    document.querySelector("#模型补充").disabled = !(数据.候选 || []).length;
    最近请求 = {...请求};
    已展示名字 = [...已展示名字, ...(数据.候选 || []).map((项目) => 项目.姓名)];
    显示八字(数据.八字);
    显示候选(数据.候选 || []);
  } catch (错误) {
    显示状态(错误.message, "错误");
  } finally {
    提交按钮.disabled = false;
    换一批按钮.disabled = false;
  }
}

起名表单.addEventListener("submit", async (事件) => {
  事件.preventDefault();
  已展示名字 = [];
  const 出生时间 = document.querySelector("#出生时间").value;
  const 请求 = {
    姓氏: document.querySelector("#姓氏").value.trim(),
    名字长度: Number(document.querySelector("#名字长度").value),
    方向: [...document.querySelectorAll("input[name=方向]:checked")].map((项) => 项.value),
    必须包含: document.querySelector("#必须包含").value.trim(),
    避用字: document.querySelector("#避用字").value.trim(),
    五行偏好: [...document.querySelectorAll("input[name=五行]:checked")].map((项) => 项.value),
    随机种子: Math.floor(Math.random() * 2147483647),
    排除名字: [],
  };
  if (出生时间) {
    请求.出生时间 = 出生时间;
    请求.时区 = document.querySelector("#时区").value.trim() || "Asia/Shanghai";
    请求.日界规则 = document.querySelector("#日界规则").value;
  }
  await 执行起名(请求);
});

换一批按钮.addEventListener("click", async () => {
  if (!最近请求) return;
  await 执行起名({
    ...最近请求,
    随机种子: Math.floor(Math.random() * 2147483647),
    排除名字: 已展示名字.slice(-100),
  });
});

结果列表.addEventListener("click", async (事件) => {
  const 按钮 = 事件.target.closest(".收藏按钮");
  if (!按钮 || !当前任务编号) return;
  按钮.disabled = true;
  try {
    const 响应 = await 会话请求("/api/favorites", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        collection_id: 收藏夹编号,
        run_id: 当前任务编号,
        full_name: 按钮.dataset.name,
      }),
    });
    const 数据 = await 响应.json();
    if (!响应.ok) throw new Error(数据.detail || "收藏失败");
    按钮.textContent = "已收藏";
  } catch (错误) {
    按钮.disabled = false;
    显示状态(错误.message, "错误");
  }
});

结果列表.addEventListener("click", async (事件) => {
  const 按钮 = 事件.target.closest(".反馈按钮");
  if (!按钮 || !当前任务编号) return;
  const 操作区 = 按钮.closest(".反馈操作");
  const 名字 = 操作区.dataset.name;
  [...操作区.querySelectorAll(".反馈按钮")].forEach((项目) => 项目.disabled = true);
  try {
    const 响应 = await 会话请求("/api/feedback", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        collection_id: 收藏夹编号,
        run_id: 当前任务编号,
        full_name: 名字,
        feedback_type: 按钮.dataset.feedback,
      }),
    });
    const 数据 = await 响应.json();
    if (!响应.ok) throw new Error(数据.detail || "反馈提交失败");
    按钮.textContent = "已提交";
    显示状态(`已记录“${按钮.dataset.feedback}”：${名字}`, "成功");
  } catch (错误) {
    [...操作区.querySelectorAll(".反馈按钮")].forEach((项目) => 项目.disabled = false);
    显示状态(错误.message, "错误");
  }
});

function 管理请求选项() {
  return {"X-Admin-Key": 管理密钥.value.trim()};
}

async function 加载复核队列() {
  复核列表.innerHTML = "正在加载……";
  const 响应 = await 会话请求("/api/admin/review-queue?数量=20", {
    headers: 管理请求选项(),
  });
  const 数据 = await 响应.json();
  if (!响应.ok) throw new Error(数据.detail || "复核队列读取失败");
  if (!数据.片段.length) {
    复核列表.innerHTML = "<p>当前没有待核验片段。</p>";
    return;
  }
  复核列表.innerHTML = 数据.片段.map((项目) => `
    <article class="复核卡片">
      <strong>${转义(项目.book)} · ${转义(项目.section_title)} · ${转义(项目.id)}</strong>
      <p>${转义(项目.text)}</p>
      <small>原始行：${转义(项目.source_line_start)}-${转义(项目.source_line_end)}</small>
      <div class="复核按钮组">
        <button class="复核按钮" data-id="${转义(项目.id)}" data-state="已核验">通过复核</button>
        <button class="复核按钮" data-id="${转义(项目.id)}" data-state="不采用">不采用</button>
      </div>
    </article>
  `).join("");
}

async function 加载质量统计() {
  质量统计.textContent = "正在加载……";
  const 响应 = await 会话请求("/api/admin/metrics", {
    headers: 管理请求选项(),
  });
  const 数据 = await 响应.json();
  if (!响应.ok) throw new Error(数据.detail || "质量统计读取失败");
  质量统计.textContent = [
    `任务 ${数据.任务总数}`,
    `候选 ${数据.候选总数}`,
    `收藏 ${数据.收藏总数}`,
    `反馈 ${数据.反馈总数}`,
    `模型调用 ${数据.模型调用总数}`,
    `待处理问题 ${数据.待处理问题数}`,
  ].join("　");
}

async function 加载任务历史() {
  历史列表.innerHTML = "正在加载……";
  const 响应 = await 会话请求("/api/name-runs?数量=20");
  const 数据 = await 响应.json();
  if (!响应.ok) throw new Error(数据.detail || "任务历史读取失败");
  if (!数据.任务.length) {
    历史列表.innerHTML = "<p>当前没有任务历史。</p>";
    return;
  }
  历史列表.innerHTML = 数据.任务.map((项目) => `
    <article class="历史卡片">
      <strong>${转义(项目.status)}</strong>
      <small>${转义(项目.created_at)}　随机种子：${转义(项目.random_seed)}</small>
      <small>任务编号：${转义(项目.id)}</small>
      <button class="历史删除按钮" data-id="${转义(项目.id)}" type="button">删除这条历史</button>
    </article>
  `).join("");
}

async function 加载年号() {
  年号列表.innerHTML = "正在加载……";
  const 参数 = new URLSearchParams({数量: "30"});
  if (年号关键词.value.trim()) 参数.set("关键词", 年号关键词.value.trim());
  if (年号地区.value.trim()) 参数.set("地区", 年号地区.value.trim());
  const 响应 = await 会话请求(`/api/eras?${参数.toString()}`);
  const 数据 = await 响应.json();
  if (!响应.ok) throw new Error(数据.detail || "年号读取失败");
  if (!数据.结果.length) {
    年号列表.innerHTML = "<p>没有找到匹配年号。</p>";
    return;
  }
  年号列表.innerHTML = 数据.结果.map((项目) => `
    <article class="年号卡片">
      <strong>${转义(项目.era_name)}</strong>
      <span>${转义(项目.region)} · ${转义(项目.category)}</span>
      <small>${转义(项目.period)} · ${转义(项目.duration)} · ${转义(项目.status)}</small>
    </article>
  `).join("");
}

async function 加载五行规则() {
  五行规则列表.innerHTML = "正在加载……";
  const 响应 = await 会话请求("/api/admin/element-queue?数量=50", {
    headers: 管理请求选项(),
  });
  const 数据 = await 响应.json();
  if (!响应.ok) throw new Error(数据.detail || "五行规则读取失败");
  if (!数据.规则.length) {
    五行规则列表.innerHTML = "<p>当前没有待复核五行规则。</p>";
    return;
  }
  五行规则列表.innerHTML = 数据.规则.map((项目) => `
    <article class="复核卡片">
      <strong>${转义(项目.char)}　${转义(项目.element)}</strong>
      <p>${转义(项目.method)} · ${转义(项目.confidence)}</p>
      <small>${转义(项目.note || "")}</small>
      <div class="复核按钮组">
        <button class="五行复核按钮" data-char="${转义(项目.char)}" data-method="${转义(项目.method)}" data-state="已核验">通过规则</button>
        <button class="五行复核按钮" data-char="${转义(项目.char)}" data-method="${转义(项目.method)}" data-state="不采用">不采用</button>
      </div>
    </article>
  `).join("");
}

async function 加载审计问题() {
  审计问题列表.innerHTML = "正在加载……";
  const 响应 = await 会话请求("/api/admin/audit-queue?数量=50", {
    headers: 管理请求选项(),
  });
  const 数据 = await 响应.json();
  if (!响应.ok) throw new Error(数据.detail || "审计问题读取失败");
  if (!数据.问题.length) {
    审计问题列表.innerHTML = "<p>当前没有待处理审计问题。</p>";
    return;
  }
  审计问题列表.innerHTML = 数据.问题.map((项目) => `
    <article class="复核卡片">
      <strong>${转义(项目.issue_type)} · ${转义(项目.file_name || "未知来源")}</strong>
      <p>${转义(项目.detail)}</p>
      <div class="复核按钮组">
        <button class="审计复核按钮" data-id="${转义(项目.id)}" data-state="已处理">标记已处理</button>
        <button class="审计复核按钮" data-id="${转义(项目.id)}" data-state="忽略">忽略问题</button>
      </div>
    </article>
  `).join("");
}

加载复核按钮.addEventListener("click", async () => {
  try {
    await 加载复核队列();
  } catch (错误) {
    复核列表.textContent = 错误.message;
  }
});

加载五行规则按钮.addEventListener("click", async () => {
  try {
    await 加载五行规则();
  } catch (错误) {
    五行规则列表.textContent = 错误.message;
  }
});

加载审计问题按钮.addEventListener("click", async () => {
  try {
    await 加载审计问题();
  } catch (错误) {
    审计问题列表.textContent = 错误.message;
  }
});

加载统计按钮.addEventListener("click", async () => {
  try {
    await 加载质量统计();
  } catch (错误) {
    质量统计.textContent = 错误.message;
  }
});

加载历史按钮.addEventListener("click", async () => {
  try {
    await 加载任务历史();
  } catch (错误) {
    历史列表.textContent = 错误.message;
  }
});

加载年号按钮.addEventListener("click", async () => {
  try {
    await 加载年号();
  } catch (错误) {
    年号列表.textContent = 错误.message;
  }
});

历史列表.addEventListener("click", async (事件) => {
  const 按钮 = 事件.target.closest(".历史删除按钮");
  if (!按钮) return;
  按钮.disabled = true;
  try {
    const 响应 = await 会话请求(`/api/name-runs/${encodeURIComponent(按钮.dataset.id)}`, {method: "DELETE"});
    const 数据 = await 响应.json();
    if (!响应.ok) throw new Error(数据.detail || "历史删除失败");
    await 加载任务历史();
    显示状态("任务历史已删除", "成功");
  } catch (错误) {
    按钮.disabled = false;
    历史列表.prepend(Object.assign(document.createElement("p"), {textContent: 错误.message}));
  }
});

复核列表.addEventListener("click", async (事件) => {
  const 按钮 = 事件.target.closest(".复核按钮");
  if (!按钮) return;
  const 复核人文字 = 复核人.value.trim();
  if (!复核人文字) {
    复核列表.prepend(Object.assign(document.createElement("p"), {textContent: "请先填写复核人。"}));
    return;
  }
  按钮.disabled = true;
  try {
    const 响应 = await 会话请求(`/api/admin/passages/${按钮.dataset.id}/review`, {
      method: "POST",
      headers: {"Content-Type": "application/json", ...管理请求选项()},
      body: JSON.stringify({状态: 按钮.dataset.state, 复核人: 复核人文字, 备注: "网页管理面板复核"}),
    });
    const 数据 = await 响应.json();
    if (!响应.ok) throw new Error(数据.detail || "片段复核失败");
    await 加载复核队列();
    await 加载质量统计();
  } catch (错误) {
    按钮.disabled = false;
    复核列表.prepend(Object.assign(document.createElement("p"), {textContent: 错误.message}));
  }
});

五行规则列表.addEventListener("click", async (事件) => {
  const 按钮 = 事件.target.closest(".五行复核按钮");
  if (!按钮) return;
  const 复核人文字 = 复核人.value.trim();
  if (!复核人文字) {
    五行规则列表.prepend(Object.assign(document.createElement("p"), {textContent: "请先填写复核人。"}));
    return;
  }
  按钮.disabled = true;
  try {
    const 响应 = await 会话请求(`/api/admin/characters/${encodeURIComponent(按钮.dataset.char)}/element-review`, {
      method: "POST",
      headers: {"Content-Type": "application/json", ...管理请求选项()},
      body: JSON.stringify({
        方法: 按钮.dataset.method,
        状态: 按钮.dataset.state,
        复核人: 复核人文字,
        备注: "网页管理面板复核",
      }),
    });
    const 数据 = await 响应.json();
    if (!响应.ok) throw new Error(数据.detail || "五行规则复核失败");
    await 加载五行规则();
    await 加载质量统计();
  } catch (错误) {
    按钮.disabled = false;
    五行规则列表.prepend(Object.assign(document.createElement("p"), {textContent: 错误.message}));
  }
});

审计问题列表.addEventListener("click", async (事件) => {
  const 按钮 = 事件.target.closest(".审计复核按钮");
  if (!按钮) return;
  const 复核人文字 = 复核人.value.trim();
  if (!复核人文字) {
    审计问题列表.prepend(Object.assign(document.createElement("p"), {textContent: "请先填写复核人。"}));
    return;
  }
  按钮.disabled = true;
  try {
    const 响应 = await 会话请求(`/api/admin/audit-issues/${按钮.dataset.id}/review`, {
      method: "POST",
      headers: {"Content-Type": "application/json", ...管理请求选项()},
      body: JSON.stringify({状态: 按钮.dataset.state, 复核人: 复核人文字, 备注: "网页管理面板复核"}),
    });
    const 数据 = await 响应.json();
    if (!响应.ok) throw new Error(数据.detail || "审计问题复核失败");
    await 加载审计问题();
    await 加载质量统计();
  } catch (错误) {
    按钮.disabled = false;
    审计问题列表.prepend(Object.assign(document.createElement("p"), {textContent: 错误.message}));
  }
});

读取方向().catch((错误) => 显示状态(`方向读取失败：${错误.message}`, "错误"));
})().catch(错误 => { document.querySelector("#状态").textContent = `页面初始化失败：${错误.message}。请使用 HTTPS 或本机地址。`; });
