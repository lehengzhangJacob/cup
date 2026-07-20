const path = require("path");
const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "卧薪尝胆团队";
pres.company = "华南师范大学";
pres.subject = "第十五届中国软件杯 A5 景区导览服务 AI 数字人";
pres.title = "灵山小向导——景区导览服务 AI 数字人";
pres.lang = "zh-CN";
pres.theme = {
  headFontFace: "Microsoft YaHei",
  bodyFontFace: "Microsoft YaHei",
  lang: "zh-CN",
};
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: "F5EDD6" },
  objects: [],
});

const ROOT = path.resolve(__dirname, "..");
const ASSET = path.join(__dirname, "manual-assets");
const DIAGRAM = path.join(__dirname, "diagrams");
const OUTPUT = path.join(__dirname, "A5-灵山小向导-产品方案介绍-重制版.pptx");
const F = "Microsoft YaHei";
const W = 13.333;
const H = 7.5;

// Theme 3 — 墨绿暖沙（skill palette, verbatim semantic roles）
const C = {
  darkBg: "1A2E20",
  sectionBg: "233B2A",
  cream: "F5EDD6",
  white: "FFFFFF",
  orange: "E8734A",
  blue: "5B9E8C",
  teal: "3A8C7A",
  green: "6AB870",
  textDark: "1A2E20",
  textLight: "F5EDD6",
  muted: "8A9E90",
  divider: "2E4E38",
  cardBorder: "E0D4B8",
};
const X = {
  paper: "FFFDF8",
  soft: "ECE4D2",
  gold: "B78635",
  red: "A54537",
  slate: "50635B",
  paleGreen: "E5EEE8",
  paleCoral: "F4DDD3",
  paleBlue: "DDEAE6",
  black: "0F1814",
};

const IMG = {
  visitorHome: { path: path.join(ASSET, "01-visitor-home.png"), w: 1600, h: 1000 },
  visitorRoute: { path: path.join(ASSET, "02-visitor-route.png"), w: 1600, h: 1000 },
  visitorLocation: { path: path.join(ASSET, "03-visitor-location.png"), w: 1600, h: 1000 },
  visitorFeedback: { path: path.join(ASSET, "04-visitor-feedback-and-emotion.png"), w: 1600, h: 1000 },
  adminOverview: { path: path.join(ASSET, "06-admin-overview.png"), w: 1600, h: 1000 },
  adminKnowledge: { path: path.join(ASSET, "07-admin-knowledge.png"), w: 1600, h: 1000 },
  adminAvatar: { path: path.join(ASSET, "09-admin-avatar.png"), w: 1600, h: 1000 },
  adminReports: { path: path.join(ASSET, "10-admin-reports.png"), w: 1600, h: 1000 },
  adminHistorical: { path: path.join(ASSET, "11-admin-historical-data.png"), w: 1600, h: 1000 },
  adminEmotion: { path: path.join(ASSET, "12-admin-emotion-analysis.png"), w: 1600, h: 1000 },
  architecture: { path: path.join(DIAGRAM, "02-system-architecture.svg"), w: 1450, h: 1050 },
  avatar: { path: path.join(ROOT, "LiveTalking/data/avatars/lingshan_guide_v2/full_imgs/00000000.png"), w: 576, h: 768 },
};

function imgFit(imgKey, boxX, boxY, boxW, boxH) {
  const { path: imgPath, w: origW, h: origH } = IMG[imgKey];
  const ratio = Math.min(boxW / origW, boxH / origH);
  const w = Number((origW * ratio).toFixed(3));
  const h = Number((origH * ratio).toFixed(3));
  const x = Number((boxX + (boxW - w) / 2).toFixed(3));
  const y = Number((boxY + (boxH - h) / 2).toFixed(3));
  return { path: imgPath, x, y, w, h };
}

function text(slide, value, x, y, w, h, options = {}) {
  slide.addText(value, {
    x, y, w, h,
    fontFace: F,
    fontSize: options.fontSize ?? 15,
    color: options.color ?? C.textDark,
    bold: options.bold ?? false,
    align: options.align ?? "left",
    valign: options.valign ?? "mid",
    margin: options.margin ?? 0,
    breakLine: false,
    fit: "shrink",
    paraSpaceAfterPt: options.paraSpaceAfterPt ?? 0,
    bullet: options.bullet,
    isTextBox: true,
    ...options,
  });
}

function shape(slide, type, x, y, w, h, fill, line = fill, options = {}) {
  slide.addShape(type, {
    x, y, w, h,
    fill: fill ? { color: fill, transparency: options.transparency ?? 0 } : { color: C.white, transparency: 100 },
    line: line ? { color: line, width: options.lineWidth ?? 0.8, dash: options.dash } : { color: C.white, transparency: 100 },
    radius: options.radius,
    shadow: options.shadow,
    rotate: options.rotate,
  });
}

function line(slide, x, y, w, h, color = C.cardBorder, width = 1, endArrowType) {
  slide.addShape(pres.ShapeType.line, {
    x, y, w, h,
    line: { color, width, beginArrowType: "none", endArrowType },
  });
}

function title(slide, headline, subhead = "", dark = false, pageLabel = "") {
  const main = dark ? C.textLight : C.textDark;
  const muted = dark ? "AFC2B6" : C.muted;
  shape(slide, pres.ShapeType.rect, 0.62, 0.42, 0.08, 0.55, C.orange, C.orange);
  text(slide, headline, 0.88, 0.34, 10.95, 0.62, { fontSize: 27, bold: true, color: main });
  if (subhead) text(slide, subhead, 0.9, 0.93, 11.55, 0.34, { fontSize: 11.5, color: muted });
  if (pageLabel) text(slide, pageLabel, 11.82, 0.43, 0.83, 0.26, { fontSize: 9.5, bold: true, color: C.orange, align: "right", charSpacing: 1.3 });
  line(slide, 0.68, 1.31, 11.97, 0, dark ? C.divider : C.cardBorder, 0.8);
}

function footer(slide, page, dark = false) {
  text(slide, "第十五届中国软件杯 · A5 景区导览服务 AI 数字人", 0.68, 7.08, 6.8, 0.2, { fontSize: 8.5, color: dark ? "81988A" : C.muted });
  text(slide, String(page).padStart(2, "0"), 12.22, 7.06, 0.42, 0.2, { fontSize: 9, bold: true, color: C.orange, align: "right" });
}

function card(slide, x, y, w, h, fill = X.paper, border = C.cardBorder, shadow = true) {
  shape(slide, pres.ShapeType.roundRect, x, y, w, h, fill, border, {
    lineWidth: 0.8,
    shadow: shadow ? { type: "outer", color: "173D34", blur: 1.4, angle: 45, distance: 1.2, opacity: 0.12 } : undefined,
  });
}

function tag(slide, label, x, y, w, fill = C.divider, color = C.textLight) {
  shape(slide, pres.ShapeType.roundRect, x, y, w, 0.34, fill, fill, { lineWidth: 0 });
  text(slide, label, x + 0.06, y + 0.03, w - 0.12, 0.27, { fontSize: 9.5, bold: true, color, align: "center" });
}

function metric(slide, x, y, w, h, number, label, note, accent = C.orange, dark = false) {
  const fill = dark ? C.sectionBg : X.paper;
  const border = dark ? C.divider : C.cardBorder;
  card(slide, x, y, w, h, fill, border, true);
  text(slide, number, x + 0.18, y + 0.14, w - 0.36, 0.62, { fontSize: 27, bold: true, color: accent, align: "center" });
  text(slide, label, x + 0.16, y + 0.78, w - 0.32, 0.3, { fontSize: 11.5, bold: true, color: dark ? C.textLight : C.textDark, align: "center" });
  if (note) text(slide, note, x + 0.16, y + 1.11, w - 0.32, h - 1.22, { fontSize: 8.5, color: dark ? "AFC2B6" : C.muted, align: "center", valign: "top" });
}

function browserFrame(slide, imgKey, x, y, w, h, label = "产品运行截图") {
  card(slide, x, y, w, h, C.white, C.cardBorder, true);
  shape(slide, pres.ShapeType.rect, x, y, w, 0.3, X.soft, X.soft, { lineWidth: 0 });
  [C.orange, X.gold, C.green].forEach((color, index) => shape(slide, pres.ShapeType.ellipse, x + 0.16 + index * 0.18, y + 0.1, 0.08, 0.08, color, color, { lineWidth: 0 }));
  text(slide, label, x + 0.7, y + 0.07, w - 0.85, 0.15, { fontSize: 7.5, color: C.muted, align: "right" });
  slide.addImage(imgFit(imgKey, x + 0.12, y + 0.4, w - 0.24, h - 0.52));
}

function pillNumber(slide, value, x, y, fill = C.orange, color = C.white) {
  shape(slide, pres.ShapeType.ellipse, x, y, 0.46, 0.46, fill, fill, { lineWidth: 0 });
  text(slide, value, x, y + 0.01, 0.46, 0.42, { fontSize: 11.5, bold: true, color, align: "center" });
}

function note(slide, value) {
  slide.addNotes(value);
}

// 01 — Cover
{
  const slide = pres.addSlide();
  slide.background = { color: C.darkBg };
  shape(slide, pres.ShapeType.ellipse, 9.18, -1.25, 5.55, 5.55, C.sectionBg, C.divider, { transparency: 15, lineWidth: 1.2 });
  shape(slide, pres.ShapeType.ellipse, 10.18, -0.38, 3.85, 3.85, C.darkBg, C.divider, { transparency: 100, lineWidth: 1.2 });
  text(slide, "第十五届中国软件杯 · A5 赛题", 0.82, 0.72, 5.8, 0.34, { fontSize: 12.5, bold: true, color: "AFC2B6", charSpacing: 1.4 });
  shape(slide, pres.ShapeType.rect, 0.82, 1.26, 0.8, 0.07, C.orange, C.orange, { lineWidth: 0 });
  text(slide, "灵山小向导", 0.82, 1.62, 6.4, 0.92, { fontSize: 48, bold: true, color: C.textLight });
  text(slide, "景区导览服务 AI 数字人", 0.82, 2.57, 6.5, 0.58, { fontSize: 25, bold: true, color: C.orange });
  text(slide, "让每位游客拥有一位会理解、会讲解、会反馈的专属数字人导游", 0.85, 3.42, 5.92, 0.92, { fontSize: 17, color: "D5DFD8", breakLine: false, valign: "top" });
  tag(slide, "语音 · 文本 · 表情", 0.85, 4.72, 1.82, C.divider);
  tag(slide, "本地 RAG", 2.82, 4.72, 1.2, C.divider);
  tag(slide, "识景定位", 4.17, 4.72, 1.22, C.divider);
  tag(slide, "运营洞察", 5.54, 4.72, 1.22, C.divider);
  browserFrame(slide, "visitorHome", 7.12, 1.08, 5.5, 4.62, "游客交互端 · 实际运行");
  text(slide, "华南师范大学    ·    卧薪尝胆团队    ·    指导教师：麦思杰 教授", 0.85, 6.59, 8.4, 0.3, { fontSize: 10.5, color: "8FA394" });
  text(slide, "2026", 11.85, 6.58, 0.72, 0.28, { fontSize: 10.5, bold: true, color: C.orange, align: "right", charSpacing: 1.5 });
  note(slide, "国家正在推进文旅产业数字化转型。我们的目标不是再做一个录音播放器，而是把数字人、可靠知识问答、个性化导览和游客洞察整合成一套可落地的景区服务系统。");
}

// 02 — Agenda / judging map
{
  const slide = pres.addSlide("CONTENT");
  title(slide, "评委真正关心的，是四个问题", "用评分项组织叙事：先证明做全，再证明做深，最后证明可落地", false, "OVERVIEW");
  const cards = [
    { n: "01", score: "40%", title: "功能是否完整", body: "游客端 + 管理端\n问答、路线、识景、定位、反馈", color: C.orange },
    { n: "02", score: "30%", title: "技术是否可信", body: "数字人驱动 + 本地 RAG\n多模态情感 + 动态模型路由", color: C.blue },
    { n: "03", score: "20%", title: "体验是否自然", body: "流式首句、语义分句\n口型同步、低置信度确认", color: C.teal },
    { n: "04", score: "10%", title: "作品是否可交付", body: "源码、部署手册、设计文档\nAPK、视频与可复现实测", color: C.green },
  ];
  cards.forEach((item, i) => {
    const x = 0.72 + i * 3.13;
    card(slide, x, 1.72, 2.82, 3.92, i === 0 ? C.darkBg : X.paper, i === 0 ? C.divider : C.cardBorder, true);
    text(slide, item.n, x + 0.2, 1.92, 0.6, 0.3, { fontSize: 10, bold: true, color: item.color, charSpacing: 1.6 });
    text(slide, item.score, x + 0.22, 2.38, 2.35, 0.76, { fontSize: 32, bold: true, color: item.color });
    text(slide, item.title, x + 0.22, 3.27, 2.36, 0.45, { fontSize: 17, bold: true, color: i === 0 ? C.textLight : C.textDark });
    line(slide, x + 0.22, 3.89, 2.3, 0, i === 0 ? C.divider : C.cardBorder, 0.8);
    text(slide, item.body, x + 0.22, 4.12, 2.32, 1.02, { fontSize: 11.5, color: i === 0 ? "C8D5CD" : C.muted, valign: "top", breakLine: true, breakLineOnOverflow: false });
  });
  text(slide, "叙事主线", 0.75, 6.22, 1.05, 0.3, { fontSize: 10, bold: true, color: C.orange, charSpacing: 1.3 });
  text(slide, "行业痛点  →  产品闭环  →  核心技术  →  运行证据  →  景区价值", 1.82, 6.16, 10.65, 0.42, { fontSize: 16, bold: true, color: C.textDark });
  footer(slide, 2);
  note(slide, "接下来的内容严格对应赛题评分。我们会用真实产品页面、真实测试数字和明确的技术边界回答这四个问题。");
}

// 03 — Pain
{
  const slide = pres.addSlide("CONTENT");
  title(slide, "景区缺的不是又一台讲解器，而是一位可规模化的导游", "传统导览的四个断点，分别发生在供给、互动、情感和运营环节", false, "PROBLEM");
  const pains = [
    { n: "01", title: "旺季供给断点", body: "专业导游供不应求，服务容量随人力线性增长。", impact: "游客等待 / 景区成本", color: C.orange },
    { n: "02", title: "知识互动断点", body: "录音内容固定，无法回答追问，也无法随资料更新。", impact: "单向播放 / 信息滞后", color: C.blue },
    { n: "03", title: "情感体验断点", body: "设备听不出情绪，也不会用语气、表情作出回应。", impact: "缺少连接 / 不够自然", color: C.teal },
    { n: "04", title: "运营数据断点", body: "问题、评价和情绪散落，管理者难以量化改进。", impact: "看不见需求 / 难决策", color: C.green },
  ];
  pains.forEach((item, i) => {
    const x = i % 2 === 0 ? 0.72 : 6.83;
    const y = i < 2 ? 1.62 : 3.95;
    card(slide, x, y, 5.78, 1.93, X.paper, C.cardBorder, true);
    pillNumber(slide, item.n, x + 0.25, y + 0.26, item.color);
    text(slide, item.title, x + 0.9, y + 0.22, 3.65, 0.42, { fontSize: 17.5, bold: true });
    tag(slide, item.impact, x + 3.93, y + 0.24, 1.55, X.soft, C.textDark);
    text(slide, item.body, x + 0.25, y + 0.86, 5.1, 0.68, { fontSize: 12.5, color: C.muted, valign: "top" });
  });
  shape(slide, pres.ShapeType.roundRect, 0.72, 6.28, 11.89, 0.48, C.darkBg, C.darkBg, { lineWidth: 0 });
  text(slide, "目标：把 7×24 小时服务、个性化体验和游客洞察放进同一条闭环", 0.98, 6.34, 11.36, 0.3, { fontSize: 14.5, bold: true, color: C.textLight, align: "center" });
  footer(slide, 3);
  note(slide, "这四个痛点不能只解决其中一个。只有游客端与管理端连成闭环，数字人才从展示效果变成真正的景区生产力。");
}

// 04 — Product closed loop
{
  const slide = pres.addSlide();
  slide.background = { color: C.darkBg };
  title(slide, "一个数字人，把游客体验与景区运营连成闭环", "游客每一次提问、定位、识景和评价，都能成为下一轮服务优化的依据", true, "SOLUTION");
  const steps = [
    { n: "1", title: "理解游客", body: "语音 / 文本\n兴趣 / 当前位置", color: C.orange },
    { n: "2", title: "可靠讲解", body: "RAG 引用\n路线与景点知识", color: C.blue },
    { n: "3", title: "自然表达", body: "TTS / 口型\n语气与表情", color: C.teal },
    { n: "4", title: "记录感受", body: "情绪 / 满意度\n关注点与反馈", color: C.green },
    { n: "5", title: "运营优化", body: "知识更新\n服务建议与看板", color: X.gold },
  ];
  steps.forEach((item, i) => {
    const x = 0.75 + i * 2.47;
    const y = i % 2 === 0 ? 2.0 : 3.48;
    card(slide, x, y, 2.05, 1.62, C.sectionBg, C.divider, false);
    pillNumber(slide, item.n, x + 0.18, y + 0.18, item.color);
    text(slide, item.title, x + 0.72, y + 0.18, 1.15, 0.38, { fontSize: 15, bold: true, color: C.textLight });
    text(slide, item.body, x + 0.2, y + 0.77, 1.64, 0.62, { fontSize: 10.5, color: "B8CABF", valign: "top", align: "center" });
    if (i < steps.length - 1) line(slide, x + 2.05, y + 0.81, 0.44, i % 2 === 0 ? 1.47 : -1.47, item.color, 1.8, "triangle");
  });
  shape(slide, pres.ShapeType.roundRect, 3.95, 5.65, 5.45, 0.65, C.orange, C.orange, { lineWidth: 0 });
  text(slide, "游客得到更懂自己的导游   ·   景区得到可行动的数据", 4.18, 5.81, 5.0, 0.31, { fontSize: 14, bold: true, color: C.white, align: "center" });
  text(slide, "游客交互端", 0.8, 6.55, 2.2, 0.27, { fontSize: 10.5, bold: true, color: C.orange });
  text(slide, "管理运营端", 10.34, 6.55, 2.2, 0.27, { fontSize: 10.5, bold: true, color: C.green, align: "right" });
  footer(slide, 4, true);
  note(slide, "闭环从理解游客开始，以运营优化结束，再反哺下一次服务。系统既面对游客，也面对景区管理者。");
}

// 05 — Visitor product
{
  const slide = pres.addSlide("CONTENT");
  title(slide, "游客端不是聊天框，而是一张完整的游览工作台", "问答、路线、识景、定位四个入口共享同一个数字人与同一份景区知识", false, "PRODUCT");
  browserFrame(slide, "visitorHome", 0.62, 1.58, 7.15, 4.63, "游客端 · 数字人问答");
  browserFrame(slide, "visitorRoute", 8.02, 1.58, 4.66, 2.23, "个性化路线");
  browserFrame(slide, "visitorLocation", 8.02, 4.0, 4.66, 2.21, "多源定位");
  const features = ["实时问答", "历史 / 自然 / 亲子路线", "摄像头识景", "GPS / 二维码 / Wi-Fi / 手动定位"];
  features.forEach((label, i) => tag(slide, label, 0.75 + i * 2.72, 6.48, i === 3 ? 2.86 : 2.35, i % 2 === 0 ? C.darkBg : X.soft, i % 2 === 0 ? C.textLight : C.textDark));
  footer(slide, 5);
  note(slide, "游客可以从文字或语音开始，也可以按兴趣生成路线、拍照识景、使用当前位置或景点码。所有入口最终都进入同一个有知识依据的讲解链路。");
}

// 06 — Architecture
{
  const slide = pres.addSlide("CONTENT");
  title(slide, "多模型各司其职，不让一个大模型承担所有风险", "网关统一会话与权限；检索、生成、视觉、语音、情感和数字人按能力解耦", false, "SYSTEM");
  card(slide, 0.55, 1.52, 8.35, 5.13, X.paper, C.cardBorder, true);
  slide.addImage(imgFit("architecture", 0.7, 1.7, 8.05, 4.78));
  const stack = [
    { title: "生成路线", body: "云端 GLM\nQwen3-1.7B 轻量本地\nQwen2-7B 完整本地", color: C.orange },
    { title: "感知与表达", body: "GLM-4V + SigLIP/CLIP\nASR + TTS\nHumanOmni 七类情绪", color: C.blue },
    { title: "数字人驱动", body: "LiveTalking / Wav2Lip\nLive2D 情感表情回退\nWebRTC 实时传输", color: C.teal },
    { title: "数据资产", body: "BGE-M3 + FAISS\nSQLite 实时记录\n140,447 条历史访问数据", color: C.green },
  ];
  stack.forEach((item, i) => {
    const y = 1.54 + i * 1.28;
    card(slide, 9.15, y, 3.53, 1.04, i === 0 ? C.darkBg : X.paper, i === 0 ? C.divider : C.cardBorder, false);
    shape(slide, pres.ShapeType.rect, 9.15, y, 0.08, 1.04, item.color, item.color, { lineWidth: 0 });
    text(slide, item.title, 9.42, y + 0.12, 1.12, 0.28, { fontSize: 12.5, bold: true, color: i === 0 ? C.textLight : C.textDark });
    text(slide, item.body, 10.58, y + 0.11, 1.83, 0.74, { fontSize: 9.2, color: i === 0 ? "C7D6CD" : C.muted, valign: "top" });
  });
  tag(slide, "动态选卡", 9.23, 6.0, 1.0, C.orange);
  tag(slide, "按需加载", 10.39, 6.0, 1.0, C.blue);
  tag(slide, "空闲释放", 11.55, 6.0, 1.0, C.green);
  footer(slide, 6);
  note(slide, "架构上不把所有能力塞进一个模型。文本生成有三条路线；视觉、情感、语音和数字人各自独立，模型失败时可以明确降级而不是让整套系统崩溃。");
}

// 07 — RAG
{
  const slide = pres.addSlide("CONTENT");
  title(slide, "回答必须有出处；不知道时必须拒答", "本地景区知识库负责事实边界，生成模型负责把检索证据组织成自然讲解", false, "RAG");
  const nodes = [
    { x: 0.72, title: "权威资料", body: "DOCX / TXT\n管理员上传", color: C.orange },
    { x: 3.13, title: "本地索引", body: "BGE-M3\nFAISS 向量检索", color: C.blue },
    { x: 5.54, title: "上下文约束", body: "景点 / 兴趣 / 历史\n引用片段与拒答", color: C.teal },
    { x: 7.95, title: "三路生成", body: "GLM / Qwen3-1.7B\nQwen2-7B", color: C.green },
    { x: 10.36, title: "可追溯回答", body: "流式文本 + 引用\n会话与响应时间", color: X.gold },
  ];
  nodes.forEach((item, i) => {
    card(slide, item.x, 1.67, 2.1, 1.62, i === 4 ? C.darkBg : X.paper, i === 4 ? C.divider : C.cardBorder, false);
    shape(slide, pres.ShapeType.rect, item.x, 1.67, 2.1, 0.08, item.color, item.color, { lineWidth: 0 });
    text(slide, item.title, item.x + 0.15, 1.93, 1.8, 0.36, { fontSize: 14.5, bold: true, color: i === 4 ? C.textLight : C.textDark, align: "center" });
    text(slide, item.body, item.x + 0.14, 2.43, 1.82, 0.58, { fontSize: 10, color: i === 4 ? "C6D3CB" : C.muted, align: "center", valign: "top" });
    if (i < nodes.length - 1) line(slide, item.x + 2.1, 2.48, 0.31, 0, item.color, 1.6, "triangle");
  });
  metric(slide, 0.72, 3.78, 2.48, 1.72, "97", "当前知识片段", "管理端实时显示，可上传后自动重建索引", C.orange);
  metric(slide, 3.43, 3.78, 2.48, 1.72, "15 / 15", "事实题冒烟基线", "关键词自动化预检，不等同赛题最终准确率", C.blue);
  metric(slide, 6.14, 3.78, 2.48, 1.72, "85", "冻结评测题", "覆盖拒答、冲突、跨景区与提示注入", C.teal);
  metric(slide, 8.85, 3.78, 3.83, 1.72, "3 路", "云端 + 两级本地模型", "7B 显存不足时可切换 1.7B；OOM 明确报错", C.green);
  shape(slide, pres.ShapeType.roundRect, 0.72, 5.83, 11.96, 0.72, X.paleCoral, C.orange, { lineWidth: 0.8 });
  text(slide, "边界声明", 0.95, 6.03, 1.0, 0.26, { fontSize: 11, bold: true, color: X.red });
  text(slide, "15/15 仅证明当前小规模自动化基线通过；最终准确率仍需专家标准测试集人工复核。", 1.88, 5.96, 10.3, 0.37, { fontSize: 12.5, bold: true, color: C.textDark });
  footer(slide, 7);
  note(slide, "RAG 的重点不是一句回答听起来像真的，而是事实来自哪里、回答失败时如何拒答、更新资料后能否立即生效。这里所有测试数字都保留评测口径。");
}

// 08 — Multimodal digital human & emotion
{
  const slide = pres.addSlide();
  slide.background = { color: C.darkBg };
  title(slide, "数字人既要会说，也要听出游客的情绪", "拟真口型负责沉浸感；情绪标签负责回复语气、语速与 Live2D 表情", true, "EMOTION");
  card(slide, 0.72, 1.58, 3.42, 4.95, C.sectionBg, C.divider, false);
  slide.addImage(imgFit("avatar", 1.13, 1.81, 2.6, 3.4));
  text(slide, "拟真数字人", 1.15, 5.32, 2.56, 0.34, { fontSize: 17, bold: true, color: C.textLight, align: "center" });
  text(slide, "Wav2Lip 口型同步 · WebRTC 实时播放", 1.08, 5.78, 2.72, 0.32, { fontSize: 10.5, color: "B9CABF", align: "center" });
  const flow = [
    { label: "游客语音 / 文本", color: C.orange },
    { label: "ASR + 对话文本", color: C.blue },
    { label: "七类情绪 / 倾向", color: C.teal },
    { label: "RAG 回答 + 反应策略", color: C.green },
    { label: "TTS 语气 / 口型 / 表情", color: X.gold },
  ];
  flow.forEach((item, i) => {
    const y = 1.66 + i * 0.91;
    shape(slide, pres.ShapeType.roundRect, 4.65, y, 3.15, 0.61, i === 2 ? item.color : C.sectionBg, item.color, { lineWidth: 1.2 });
    text(slide, item.label, 4.86, y + 0.12, 2.73, 0.34, { fontSize: 12.5, bold: true, color: C.textLight, align: "center" });
    if (i < flow.length - 1) line(slide, 6.22, y + 0.61, 0, 0.3, item.color, 1.3, "triangle");
  });
  card(slide, 8.35, 1.58, 4.27, 2.16, C.sectionBg, C.divider, false);
  text(slide, "授权语音的多模态分析", 8.62, 1.84, 3.72, 0.38, { fontSize: 16, bold: true, color: C.textLight });
  text(slide, "HumanOmni 微调模型\n音频原声 + ASR 文本 → 七类情绪\n原始音频默认分析后删除", 8.62, 2.42, 3.62, 0.9, { fontSize: 11.5, color: "C4D2C9", valign: "top" });
  card(slide, 8.35, 3.98, 4.27, 2.55, C.sectionBg, C.divider, false);
  text(slide, "情感交互不是假装识别人脸", 8.62, 4.24, 3.72, 0.38, { fontSize: 16, bold: true, color: C.orange });
  text(slide, "文本对话持续分析关注点与倾向；只有游客明确授权语音时，才运行音频—文本模型。情绪结果驱动回复前缀、语速和表情模式。", 8.62, 4.88, 3.55, 1.16, { fontSize: 11.2, color: "C4D2C9", valign: "top" });
  footer(slide, 8, true);
  note(slide, "多模态情绪来自游客与数字人的真实对话，不需要管理员上传视频。游客未授权时只做文本分析；授权语音时结合原声和 ASR 文本，媒体默认删除。");
}

// 09 — Recognition & positioning
{
  const slide = pres.addSlide("CONTENT");
  title(slide, "识景不赌单模型，定位不赌单信号", "把低置信度当作产品状态：给候选、要确认、可纠错，再开始有依据的讲解", false, "PERCEPTION");
  browserFrame(slide, "visitorLocation", 0.62, 1.55, 6.38, 4.52, "游客端 · 多源定位");
  const visionSteps = [
    { title: "候选召回", body: "GLM-4V 提取画面线索\n只允许返回本地景点目录", color: C.orange },
    { title: "参考图复核", body: "SigLIP / CLIP 与授权图库比对\n位置只作为弱先验", color: C.blue },
    { title: "置信度门控", body: "高置信度直接提示\n中低置信度要求游客确认", color: C.teal },
    { title: "确认后讲解", body: "纠错写入评测记录\nRAG 对确认景点提供引用", color: C.green },
  ];
  visionSteps.forEach((item, i) => {
    const y = 1.57 + i * 1.18;
    card(slide, 7.35, y, 5.29, 0.94, i === 2 ? C.darkBg : X.paper, i === 2 ? C.divider : C.cardBorder, false);
    pillNumber(slide, String(i + 1), 7.58, y + 0.24, item.color);
    text(slide, item.title, 8.22, y + 0.18, 1.45, 0.31, { fontSize: 13, bold: true, color: i === 2 ? C.textLight : C.textDark });
    text(slide, item.body, 9.72, y + 0.14, 2.57, 0.6, { fontSize: 9.7, color: i === 2 ? "C4D2C9" : C.muted, valign: "top" });
  });
  text(slide, "定位降级顺序", 7.42, 6.35, 1.28, 0.28, { fontSize: 10.5, bold: true, color: C.orange });
  text(slide, "GPS  →  景点二维码  →  景区 Wi-Fi / 信标  →  手动选择", 8.83, 6.29, 3.72, 0.38, { fontSize: 12.2, bold: true });
  footer(slide, 9);
  note(slide, "识景准确率低时，产品不能硬猜。我们把视觉候选、本地参考图、位置先验和游客确认组合起来；定位也提供二维码、Wi-Fi 与手动选择等降级路径。");
}

// 10 — Admin dashboard
{
  const slide = pres.addSlide("CONTENT");
  title(slide, "后台把一次对话，变成可追踪的运营证据", "服务人次、热门问答、情感趋势、满意度和响应时间在同一运营视图呈现", false, "ADMIN");
  browserFrame(slide, "adminOverview", 0.62, 1.5, 8.65, 4.98, "管理后台 · 数据概览");
  const metrics = [
    { number: "42", label: "今日服务游客", note: "按会话去重", color: C.orange },
    { number: "317", label: "累计问答", note: "知识问答轮次", color: C.blue },
    { number: "3.8 / 5", label: "平均满意度", note: "游客主动评价", color: C.teal },
    { number: "2.97 s", label: "平均响应", note: "后台实时聚合", color: C.green },
  ];
  metrics.forEach((item, i) => metric(slide, 9.55, 1.54 + i * 1.22, 3.04, 1.0, item.number, item.label, item.note, item.color));
  shape(slide, pres.ShapeType.roundRect, 9.55, 6.4, 3.04, 0.42, C.darkBg, C.darkBg, { lineWidth: 0 });
  text(slide, "看趋势，也保留证据与时间范围", 9.72, 6.48, 2.7, 0.25, { fontSize: 10.5, bold: true, color: C.textLight, align: "center" });
  footer(slide, 10);
  note(slide, "后台数据不是静态假图。当前截图来自运行中的系统，指标由聊天记录、反馈、情绪事件和响应时间聚合生成。");
}

// 11 — Admin operations & emotion report
{
  const slide = pres.addSlide("CONTENT");
  title(slide, "管理端不上传游客视频，而是管理知识、形象与服务结果", "情绪来自游客对话；管理员负责维护内容、查看报告并执行改进建议", false, "OPS");
  browserFrame(slide, "adminKnowledge", 0.62, 1.5, 4.0, 2.34, "知识库：上传后重建索引");
  browserFrame(slide, "adminAvatar", 4.86, 1.5, 4.0, 2.34, "数字人：名称、声音、形象");
  browserFrame(slide, "adminEmotion", 9.1, 1.5, 3.58, 2.34, "情绪任务与七类分布");
  browserFrame(slide, "adminReports", 0.62, 4.13, 6.0, 2.3, "感受度报告：问题、评价与建议");
  browserFrame(slide, "adminHistorical", 6.86, 4.13, 5.82, 2.3, "历史数据：灵山 / 拈花湾专项统计");
  tag(slide, "真实知识更新", 0.72, 6.65, 1.35, C.orange);
  tag(slide, "形象可配置", 2.22, 6.65, 1.27, C.blue);
  tag(slide, "对话情绪", 3.64, 6.65, 1.17, C.teal);
  tag(slide, "主动满意度", 4.96, 6.65, 1.28, C.green);
  text(slide, "实时交互数据与公开 XLSX 历史数据分层展示，避免混淆统计口径", 6.55, 6.65, 6.02, 0.27, { fontSize: 10.2, bold: true, color: C.textDark, align: "right" });
  footer(slide, 11);
  note(slide, "情绪分析的输入是游客与数字人的对话。管理端不需要上传游客视频；它负责查看聚合报告、维护知识、配置数字人并落实系统建议。");
}

// 12 — Evidence and engineering
{
  const slide = pres.addSlide();
  slide.background = { color: C.darkBg };
  title(slide, "用可复现数据证明：准确、快速、稳定、可解释", "所有数字注明测试环境与口径；失败路径同样是产品能力", true, "EVIDENCE");
  metric(slide, 0.72, 1.6, 2.75, 1.72, "15 / 15", "事实题冒烟基线", "关键词自动化预检；最终准确率待专家复核", C.orange, true);
  metric(slide, 3.7, 1.6, 2.75, 1.72, "2160 ms", "数字人首响中位数", "2026-07-20 连续 4 轮；最大 2705ms", C.blue, true);
  metric(slide, 6.68, 1.6, 2.75, 1.72, "140,447", "历史访问记录", "50,000 游客 · 152 个景点", C.teal, true);
  metric(slide, 9.66, 1.6, 2.95, 1.72, "3 路", "问答模型路线", "云端 / 1.7B 轻量 / 7B 完整", C.green, true);
  const checks = [
    { title: "低延迟流水线", body: "首个完整语义短句立即进入 TTS；连续 PCM 推送数字人，不等待全文。", color: C.orange },
    { title: "GPU 生命周期", body: "请求时动态选择空闲卡；模型按需加载，空闲后释放显存。", color: C.blue },
    { title: "OOM 可见错误", body: "无达标 GPU 或真实 CUDA OOM 均返回明确错误与切换建议。", color: C.teal },
    { title: "服务降级", body: "拟真数字人失败回退 Live2D；情感模型失败保留来源与降级状态。", color: C.green },
    { title: "隐私与安全", body: "语音分析需授权；原始媒体默认删除；模型密钥不下发浏览器。", color: X.gold },
    { title: "工程可交付", body: "健康检查、自动恢复、部署手册、APK、测试脚本与日志齐备。", color: C.orange },
  ];
  checks.forEach((item, i) => {
    const x = 0.72 + (i % 3) * 4.0;
    const y = i < 3 ? 3.72 : 5.23;
    card(slide, x, y, 3.72, 1.21, C.sectionBg, C.divider, false);
    shape(slide, pres.ShapeType.rect, x, y, 0.07, 1.21, item.color, item.color, { lineWidth: 0 });
    text(slide, item.title, x + 0.25, y + 0.15, 3.15, 0.3, { fontSize: 13, bold: true, color: C.textLight });
    text(slide, item.body, x + 0.25, y + 0.54, 3.12, 0.49, { fontSize: 9.5, color: "B8C9BE", valign: "top" });
  });
  footer(slide, 12, true);
  note(slide, "最新四轮首响中位数为 2160 毫秒，低于赛题 5 秒目标。系统还把模型显存不足、数字人断连和情感模型降级变成可见、可恢复的状态。");
}

// 13 — Innovation, value and close
{
  const slide = pres.addSlide();
  slide.background = { color: C.darkBg };
  title(slide, "技术最终要落到两件事：游客愿意用，景区用得起", "从单景区演示走向可复制的文旅数字基础设施", true, "VALUE");
  const values = [
    { title: "游客体验", big: "随时可问", body: "个性化讲解、路线、识景与定位\n情绪感知让交互更亲切", color: C.orange },
    { title: "景区运营", big: "每次可学", body: "热门问题、评价与情绪形成报告\n知识与形象可持续维护", color: C.blue },
    { title: "工程成本", big: "按需使用", body: "云端与本地三级路由\n动态 GPU 降低部署门槛", color: C.teal },
  ];
  values.forEach((item, i) => {
    const x = 0.72 + i * 4.0;
    card(slide, x, 1.62, 3.73, 2.42, C.sectionBg, C.divider, false);
    text(slide, item.title, x + 0.26, 1.87, 1.2, 0.3, { fontSize: 11, bold: true, color: item.color, charSpacing: 1.1 });
    text(slide, item.big, x + 0.26, 2.36, 3.1, 0.58, { fontSize: 27, bold: true, color: C.textLight });
    text(slide, item.body, x + 0.26, 3.14, 3.05, 0.62, { fontSize: 10.5, color: "BACABF", valign: "top" });
  });
  text(slide, "下一步", 0.75, 4.58, 0.9, 0.3, { fontSize: 10.5, bold: true, color: C.orange, charSpacing: 1.4 });
  const roadmap = [
    { n: "01", title: "景区实测", body: "补齐真实坐标、BSSID / 蓝牙信标和授权参考图库" },
    { n: "02", title: "规模评测", body: "专家事实集、识景 Top-1 / Top-3 与并发容量测试" },
    { n: "03", title: "复制推广", body: "多景区、多方言、多数字人形象与小程序入口" },
  ];
  roadmap.forEach((item, i) => {
    const x = 0.75 + i * 4.0;
    pillNumber(slide, item.n, x, 5.08, i === 0 ? C.orange : i === 1 ? C.blue : C.green);
    text(slide, item.title, x + 0.64, 5.04, 1.22, 0.32, { fontSize: 13.5, bold: true, color: C.textLight });
    text(slide, item.body, x + 0.64, 5.48, 2.75, 0.58, { fontSize: 9.8, color: "ADC1B4", valign: "top" });
  });
  shape(slide, pres.ShapeType.roundRect, 0.72, 6.32, 11.89, 0.56, C.orange, C.orange, { lineWidth: 0 });
  text(slide, "让每位游客都有专属导游，让每次互动都成为运营依据", 0.98, 6.43, 11.36, 0.31, { fontSize: 16, bold: true, color: C.white, align: "center" });
  text(slide, "华南师范大学  ·  卧薪尝胆团队  ·  高曼宁 / 张乐桁 / 龙杰森  ·  指导教师：麦思杰 教授", 0.78, 7.08, 10.8, 0.2, { fontSize: 8.5, color: "81988A" });
  text(slide, "谢谢", 11.86, 7.06, 0.7, 0.2, { fontSize: 9, bold: true, color: C.orange, align: "right" });
  note(slide, "灵山小向导希望解决的不是一次演示，而是景区长期存在的服务供给与运营反馈问题。谢谢各位评委。");
}

pres.writeFile({ fileName: OUTPUT })
  .then(() => process.stdout.write(`PPTX written: ${OUTPUT}\n`))
  .catch((error) => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exit(1);
  });
