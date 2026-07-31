const path = require("path");
const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "卧薪尝胆团队";
pres.company = "华南师范大学";
pres.subject = "灵山小向导地图功能";
pres.title = "地图把路线推荐变成可执行行程";
pres.lang = "zh-CN";
pres.theme = {
  headFontFace: "Microsoft YaHei",
  bodyFontFace: "Microsoft YaHei",
  lang: "zh-CN",
};

const F = "Microsoft YaHei";
const OUTPUT = process.env.MAP_SLIDE_OUTPUT || "/tmp/cup-map-feature-slide.pptx";
const SCREENSHOT = path.join(__dirname, "manual-assets", "13-visitor-map-route.png");

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
  paleCoral: "F4DDD3",
};

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
    fit: "shrink",
    isTextBox: true,
    ...options,
  });
}

function shape(slide, type, x, y, w, h, fill, line = fill, options = {}) {
  slide.addShape(type, {
    x, y, w, h,
    fill: { color: fill, transparency: options.transparency ?? 0 },
    line: { color: line, width: options.lineWidth ?? 0.8 },
    shadow: options.shadow,
  });
}

function card(slide, x, y, w, h, fill = X.paper, border = C.cardBorder, shadow = true) {
  shape(slide, pres.ShapeType.roundRect, x, y, w, h, fill, border, {
    lineWidth: 0.8,
    shadow: shadow
      ? { type: "outer", color: "173D34", blur: 2, angle: 45, offset: 1.2, opacity: 0.12 }
      : undefined,
  });
}

function line(slide, x, y, w, h, color = C.cardBorder, width = 1) {
  slide.addShape(pres.ShapeType.line, {
    x, y, w, h,
    line: { color, width },
  });
}

function browserFrame(slide, x, y, w, h, label) {
  card(slide, x, y, w, h, C.white, C.cardBorder, true);
  shape(slide, pres.ShapeType.rect, x, y, w, 0.3, X.soft, X.soft, { lineWidth: 0 });
  [C.orange, X.gold, C.green].forEach((color, index) => {
    shape(slide, pres.ShapeType.ellipse, x + 0.16 + index * 0.18, y + 0.1, 0.08, 0.08, color, color, { lineWidth: 0 });
  });
  text(slide, label, x + 0.7, y + 0.07, w - 0.85, 0.15, {
    fontSize: 7.5,
    color: C.muted,
    align: "right",
  });
}

const slide = pres.addSlide();
slide.background = { color: C.cream };

shape(slide, pres.ShapeType.rect, 0.62, 0.42, 0.08, 0.55, C.orange, C.orange, { lineWidth: 0 });
text(slide, "地图把路线推荐变成可执行行程", 0.88, 0.34, 10.95, 0.62, {
  fontSize: 27,
  bold: true,
});
text(slide, "五类输入共同约束路线；站点顺序、时长、距离与分段导航一次呈现", 0.9, 0.93, 11.55, 0.34, {
  fontSize: 11.5,
  color: C.muted,
});
text(slide, "MAP", 11.82, 0.43, 0.83, 0.26, {
  fontSize: 9.5,
  bold: true,
  color: C.orange,
  align: "right",
  charSpacing: 1.3,
});
line(slide, 0.68, 1.31, 11.97, 0, C.cardBorder, 0.8);

browserFrame(slide, 0.62, 1.54, 7.32, 3.53, "游客端 · 路线生成结果");
slide.addImage({
  path: SCREENSHOT,
  x: 0.75,
  y: 1.94,
  w: 7.06,
  h: 3.38,
});

browserFrame(slide, 8.16, 1.54, 4.52, 3.53, "地图局部 · 站点顺序与指标");
slide.addImage({
  path: SCREENSHOT,
  x: 8.34,
  y: 1.94,
  w: 13.33,
  h: 6.39,
  sizing: {
    type: "crop",
    x: 7.82,
    y: 1.48,
    w: 4.16,
    h: 2.94,
  },
});

const steps = [
  {
    n: "01",
    title: "五类输入",
    body: "时间 · 兴趣 · 同行\n步行偏好 · 路线起点",
    color: C.orange,
  },
  {
    n: "02",
    title: "约束规划",
    body: "兴趣匹配 + 时间预算\n步行负担与景点可达性",
    color: C.blue,
  },
  {
    n: "03",
    title: "地图结果",
    body: "195 分钟 · 4 站\n1.7 km · 步行 25 分钟",
    color: C.teal,
    dark: true,
  },
  {
    n: "04",
    title: "分段导航",
    body: "编号站点 + 顺序连线\n逐段打开高德步行导航",
    color: C.green,
  },
];

steps.forEach((item, index) => {
  const x = 0.62 + index * 3.02;
  const fill = item.dark ? C.darkBg : X.paper;
  const border = item.dark ? C.divider : C.cardBorder;
  card(slide, x, 5.27, 2.82, 1.12, fill, border, false);
  text(slide, item.n, x + 0.18, 5.43, 0.45, 0.22, {
    fontSize: 9.5,
    bold: true,
    color: item.color,
    charSpacing: 1.1,
  });
  text(slide, item.title, x + 0.72, 5.37, 1.78, 0.31, {
    fontSize: 13,
    bold: true,
    color: item.dark ? C.textLight : C.textDark,
  });
  text(slide, item.body, x + 0.18, 5.78, 2.43, 0.43, {
    fontSize: 9.5,
    color: item.dark ? "C4D2C9" : C.muted,
    valign: "top",
    breakLine: true,
  });
});

shape(slide, pres.ShapeType.roundRect, 0.62, 6.56, 12.06, 0.32, X.paleCoral, C.orange, { lineWidth: 0.7 });
text(slide, "演示边界：当前 5/16 个子景点具备可核验地图点位；路线连线表示游览顺序，不替代园内步行道路导航。", 0.82, 6.61, 11.65, 0.2, {
  fontSize: 8.7,
  bold: true,
  color: C.textDark,
  align: "center",
});

text(slide, "第十五届中国软件杯 · A5 景区导览服务 AI 数字人", 0.68, 7.08, 6.8, 0.2, {
  fontSize: 8.5,
  color: C.muted,
});
text(slide, "05", 12.22, 7.06, 0.42, 0.2, {
  fontSize: 9,
  bold: true,
  color: C.orange,
  align: "right",
});

pres.writeFile({ fileName: OUTPUT })
  .then(() => process.stdout.write(`Map slide written: ${OUTPUT}\n`))
  .catch((error) => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exit(1);
  });

