/**
 * 灵曦 Live2D 模块（Haru）
 * - 加载 / 口型 / 表情 / 发色 / 服装
 * - 不包含问答与 TTS（由页面接 cup API）
 */
(function (global) {
  const HARU_MODEL_PATH = "/static/live2d/Haru/Haru.model3.json";
  const MOUTH_PARAMETER = "ParamMouthOpenY";
  const COSTUMES = new Set(["classic", "jade", "cinnabar"]);
  const HAIR_TEXTURES = {
    classic: null,
    chestnut: "/static/live2d/Haru/Haru.2048/texture_00_chestnut.png",
    ink: "/static/live2d/Haru/Haru.2048/texture_00_ink.png",
  };
  const EXPRESSIONS = {
    natural: null,
    gentle: "Gentle",
    smile: "F05",
    bright: "F06",
  };
  const EMOTION_MAP = {
    smile: "smile",
    calm: "natural",
    solemn: "gentle",
    surprise: "bright",
    natural: "natural",
    gentle: "gentle",
    bright: "bright",
  };

  const state = {
    app: null,
    model: null,
    canvas: null,
    wrap: null,
    speaking: false,
    speechStartedAt: 0,
    mouthTarget: 0,
    mouthValue: 0,
    audioLevel: 0,
    hairTextures: new Map(),
    bodyTextures: new Map(),
    currentHair: "classic",
    currentCostume: "classic",
    currentExpression: "natural",
    changingStyle: false,
    resizeObserver: null,
    ready: false,
  };

  function bodyTextureKey(costumeName, hairName) {
    return `${costumeName}:${hairName}`;
  }

  function bodyTexturePath(costumeName, hairName) {
    const basePath = "/static/live2d/Haru/Haru.2048";
    if (hairName === "classic") {
      return costumeName === "classic" ? null : `${basePath}/texture_01_${costumeName}.png`;
    }
    return `${basePath}/texture_01_${costumeName}_${hairName}.png`;
  }

  async function loadBodyTexture(costumeName, hairName) {
    const key = bodyTextureKey(costumeName, hairName);
    if (state.bodyTextures.has(key)) return state.bodyTextures.get(key);
    const texturePath = bodyTexturePath(costumeName, hairName);
    if (!texturePath) return null;
    const texture = await global.PIXI.Texture.fromURL(texturePath);
    state.bodyTextures.set(key, texture);
    return texture;
  }

  async function loadHairTexture(hairName) {
    if (state.hairTextures.has(hairName)) return state.hairTextures.get(hairName);
    const texturePath = HAIR_TEXTURES[hairName];
    if (!texturePath) return null;
    const texture = await global.PIXI.Texture.fromURL(texturePath);
    state.hairTextures.set(hairName, texture);
    return texture;
  }

  function setMouthValue(value) {
    if (!state.model?.internalModel?.coreModel) return;
    state.model.internalModel.coreModel.setParameterValueById(
      MOUTH_PARAMETER,
      Math.max(0, Math.min(1, value)),
    );
  }

  function updateLipSync() {
    const now = performance.now();
    if (state.speaking) {
      // prefer realtime audio level; fall back to envelope
      if (state.audioLevel > 0.02) {
        state.mouthTarget = Math.min(1, 0.12 + state.audioLevel * 1.35);
      } else {
        const elapsed = Math.max(0, (now - state.speechStartedAt) / 1000);
        const syllable = Math.abs(
          Math.sin(Math.PI * (elapsed * 4.5 + Math.sin(elapsed * 2.3) * 0.1)),
        );
        const phrasePosition = elapsed % 1.7;
        const phraseEnvelope = phrasePosition > 1.52 ? 0.08 : 1;
        const detail = 0.86 + Math.sin(elapsed * 10.7 + 0.4) * 0.14;
        state.mouthTarget =
          phraseEnvelope * (0.1 + Math.pow(syllable, 0.72) * 0.78) * detail;
      }
    } else {
      state.mouthTarget = 0;
    }

    const smoothing = state.mouthTarget > state.mouthValue ? 0.62 : 0.38;
    state.mouthValue += (state.mouthTarget - state.mouthValue) * smoothing;
    if (!state.speaking && state.mouthValue < 0.01) state.mouthValue = 0;
    setMouthValue(state.mouthValue);
  }

  function positionModel() {
    if (!state.model || !state.wrap) return;
    const width = state.wrap.clientWidth;
    const height = state.wrap.clientHeight;
    const modelWidth = state.model.internalModel.width || state.model.width || 1;
    const modelHeight = state.model.internalModel.height || state.model.height || 1;
    const scale = Math.min((width * 0.82) / modelWidth, (height * 1.05) / modelHeight);
    state.model.scale.set(scale);
    state.model.anchor.set(0.5, 0.52);
    state.model.position.set(width * 0.52, height * 0.56);
  }

  async function init(canvas, wrap) {
    state.canvas = canvas;
    state.wrap = wrap;

    if (!global.Live2DCubismCore) {
      throw new Error("Cubism Core 未加载");
    }
    if (!global.PIXI?.live2d?.Live2DModel) {
      throw new Error("PIXI Live2D 未加载");
    }

    const { Application } = global.PIXI;
    const { Live2DModel } = global.PIXI.live2d;

    state.app = new Application({
      view: canvas,
      resizeTo: wrap,
      backgroundAlpha: 0,
      antialias: true,
      autoDensity: true,
      resolution: Math.min(global.devicePixelRatio || 1, 2),
    });

    const model = await Live2DModel.from(HARU_MODEL_PATH, { autoInteract: false });
    state.model = model;
    state.app.stage.addChild(model);
    positionModel();
    state.hairTextures.set("classic", model.textures[0]);
    state.bodyTextures.set(bodyTextureKey("classic", "classic"), model.textures[1]);

    model.on("hit", (hitAreas) => {
      if (hitAreas.includes("Body")) model.motion("TapBody");
      const selectedExpression = EXPRESSIONS[state.currentExpression];
      if (hitAreas.includes("Head") && selectedExpression) model.expression(selectedExpression);
    });

    model.internalModel.on("beforeModelUpdate", updateLipSync);

    state.resizeObserver = new ResizeObserver(positionModel);
    state.resizeObserver.observe(wrap);
    state.ready = true;
    return true;
  }

  function setExpression(expressionName) {
    if (!state.model || !(expressionName in EXPRESSIONS)) return;
    const expression = EXPRESSIONS[expressionName];
    if (expression) {
      state.model.expression(expression);
    } else {
      state.model.internalModel.motionManager.expressionManager?.resetExpression?.();
    }
    state.currentExpression = expressionName;
  }

  function setEmotion(emotion) {
    const mapped = EMOTION_MAP[emotion] || "natural";
    setExpression(mapped);
  }

  async function setHair(hairName) {
    if (!state.model || state.changingStyle || !(hairName in HAIR_TEXTURES)) return;
    if (hairName === state.currentHair) return;
    state.changingStyle = true;
    try {
      const [hairTexture, bodyTexture] = await Promise.all([
        loadHairTexture(hairName),
        loadBodyTexture(state.currentCostume, hairName),
      ]);
      if (!hairTexture || !bodyTexture) throw new Error(`Missing hair texture: ${hairName}`);
      state.model.textures[0] = hairTexture;
      state.model.textures[1] = bodyTexture;
      state.currentHair = hairName;
    } finally {
      state.changingStyle = false;
    }
  }

  async function setCostume(costumeName) {
    if (!state.model || state.changingStyle || !COSTUMES.has(costumeName)) return;
    if (costumeName === state.currentCostume) return;
    state.changingStyle = true;
    try {
      const texture = await loadBodyTexture(costumeName, state.currentHair);
      if (!texture) throw new Error(`Missing costume texture: ${costumeName}`);
      state.model.textures[1] = texture;
      state.currentCostume = costumeName;
    } finally {
      state.changingStyle = false;
    }
  }

  function startSpeaking() {
    state.speaking = true;
    state.speechStartedAt = performance.now();
    state.audioLevel = 0;
  }

  function stopSpeaking() {
    state.speaking = false;
    state.audioLevel = 0;
    state.mouthTarget = 0;
  }

  function setMouthFromAudio(level) {
    state.audioLevel = Math.max(0, Math.min(1, level || 0));
  }

  function destroy() {
    stopSpeaking();
    state.resizeObserver?.disconnect();
    state.app?.destroy?.(true);
    state.ready = false;
  }

  global.LingxiLive2D = {
    init,
    setExpression,
    setEmotion,
    setHair,
    setCostume,
    startSpeaking,
    stopSpeaking,
    setMouthFromAudio,
    destroy,
    get ready() {
      return state.ready;
    },
    get style() {
      return {
        expression: state.currentExpression,
        hair: state.currentHair,
        costume: state.currentCostume,
      };
    },
  };
})(window);
