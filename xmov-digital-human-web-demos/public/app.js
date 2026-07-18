(function () {
  const config = window.__XMOV_CONFIG__ || {};

  const els = {
    connectBtn: document.getElementById("connectBtn"),
    generateBtn: document.getElementById("generateBtn"),
    introBtn: document.getElementById("introBtn"),
    statusPill: document.getElementById("statusPill"),
    speechCaption: document.getElementById("speechCaption"),
    avatarFallback: document.getElementById("avatarFallback"),
    summaryText: document.getElementById("summaryText"),
    targetCountry: document.getElementById("targetCountry"),
    degreeLevel: document.getElementById("degreeLevel"),
    majorTrack: document.getElementById("majorTrack"),
    intakeSeason: document.getElementById("intakeSeason"),
    budgetLevel: document.getElementById("budgetLevel"),
    profileLevel: document.getElementById("profileLevel"),
    studentNotes: document.getElementById("studentNotes"),
    planPositioning: document.getElementById("planPositioning"),
    planTimeline: document.getElementById("planTimeline"),
    planSchoolMix: document.getElementById("planSchoolMix"),
    planNextSteps: document.getElementById("planNextSteps"),
    quickPicks: Array.from(document.querySelectorAll("[data-preset]")),
  };

  const PROFESSIONAL_AVATAR_CONFIG = {
    init_events: [
      {
        type: "SetCharacterCanvasAnchor",
        x_location: 0,
        y_location: 0,
        width: 1,
        height: 1,
      },
    ],
  };

  const state = {
    avatar: null,
    connected: false,
    status: "idle",
    lastPlan: null,
    fallbackVisible: false,
    audioRecording: null,
    logs: [],
    errors: [],
  };

  window.__studyAdvisorApp = state;

  const countryPlaybook = {
    英国: {
      tone: "英国项目会更看重专业匹配、动机表达和投递节奏，文书定调要尽早完成。",
      schools: "学校组合建议拆成伦敦冲刺组、专业强匹配主申组和录取更稳的保底组。",
      timeline: "建议先完成选校与文书框架，再同步推进语言和推荐信，尽量赶在前轮投递。",
      materials: "重点准备简历、个人陈述、成绩单、语言成绩，以及能证明职业方向的实习材料。",
    },
    美国: {
      tone: "美国申请更强调背景叙事、项目经历和长期目标，不能只用排名来驱动选校。",
      schools: "建议拆成顶尖冲刺组、专业主申组和就业导向保稳组，保持学术与实务并重。",
      timeline: "优先补强科研或实习故事，再倒排语言、推荐信和文书打磨时间。",
      materials: "重点准备项目经历说明、推荐信沟通、个人陈述、简历和可量化成果。",
    },
    香港: {
      tone: "香港项目投递节奏快，很多项目滚动录取，准备越早越有优势。",
      schools: "建议划分港前三冲刺组、专业资源主申组和录取更稳的项目组。",
      timeline: "尽快完成定校、文书和语言安排，让材料形成闭环后尽早投递。",
      materials: "重点准备语言成绩、简历、推荐信、实习证明和职业规划说明。",
    },
    新加坡: {
      tone: "新加坡项目数量不多，更看重学术基础和就业转化，所以申请定位要更精确。",
      schools: "建议少而精，集中投递与专业方向高度匹配的项目，提升每份材料命中率。",
      timeline: "先确认语言和学术门槛，再快速准备简历、文书和专业匹配说明。",
      materials: "重点准备成绩单、语言成绩、简历、推荐信和相关课程或实习材料。",
    },
    澳大利亚: {
      tone: "澳洲申请更适合做稳节奏规划，要同时兼顾录取概率、预算和地区选择。",
      schools: "建议分成综合排名组、专业资源组和预算友好组，保持申请结构平衡。",
      timeline: "先梳理是否直申，再同步准备语言与申请材料，整体推进会更顺畅。",
      materials: "重点准备成绩单、语言成绩、个人陈述、简历和职业意图材料。",
    },
    德国: {
      tone: "德国项目更强调课程匹配、学术基础和申请资格要求，专业契合度影响很大。",
      schools: "建议围绕课程匹配度建立主申池，不要只看综合排名。",
      timeline: "先核查课程前置要求和语言要求，再安排认证、文书和投递节奏。",
      materials: "重点准备课程匹配说明、成绩单、动机信、语言成绩和资格认证材料。",
    },
    加拿大: {
      tone: "加拿大申请更看重稳健规划和长期发展路径，地域、预算和就业目标要一起判断。",
      schools: "建议拆成综合名校组、就业地域组和预算更稳的项目组。",
      timeline: "先确认匹配度，再安排语言、文书和推荐信，不要把关键节点压到最后。",
      materials: "重点准备成绩单、语言成绩、简历、推荐信以及未来职业方向证明材料。",
    },
  };

  const presets = {
    "uk-finance": {
      country: "英国",
      degree: "硕士",
      major: "金融 / 金融科技",
      intake: "2026 秋季",
      budget: "40-60 万人民币",
      profile: "中等背景，需要稳扎稳打",
      notes: "本科商科，GPA 3.4，有一段券商实习和一段咨询实习，希望申请就业导向更强的项目。",
    },
    "us-ai": {
      country: "美国",
      degree: "硕士",
      major: "人工智能 / 计算机",
      intake: "2026 秋季",
      budget: "60 万人民币以上",
      profile: "技术基础较强，可冲研究型项目",
      notes: "本科计算机，GPA 3.7，有两段算法实习和科研经历，希望申请 AI 方向项目。",
    },
    "hk-media": {
      country: "香港",
      degree: "硕士",
      major: "传媒 / 新媒体",
      intake: "2026 秋季",
      budget: "30-40 万人民币",
      profile: "跨专业，需要强化解释与补充经历",
      notes: "本科英语专业，有校园媒体和品牌内容运营经历，希望转向新媒体传播项目。",
    },
    "sg-analytics": {
      country: "新加坡",
      degree: "硕士",
      major: "商业分析 / 数据分析",
      intake: "2026 秋季",
      budget: "40-60 万人民币",
      profile: "数理基础扎实，可冲就业导向项目",
      notes: "本科统计学，GPA 3.6，有咨询实习和数据分析项目，希望项目兼顾就业和行业资源。",
    },
  };

  function log(message, level = "info") {
    const line = `${new Date().toLocaleTimeString()} [${level}] ${message}`;
    state.logs.push(line);
    if (level === "error") {
      console.error(line);
    } else {
      console.log(line);
    }
  }

  function setStatus(mode, text) {
    state.status = mode;
    els.statusPill.textContent = text;
    els.statusPill.className = `status-chip ${mode}`;
  }

  function setConnected(connected) {
    state.connected = connected;
    els.generateBtn.disabled = !connected;
    els.introBtn.disabled = !connected;
    els.connectBtn.disabled = connected;
    els.connectBtn.textContent = connected ? "顾问已在线" : "接入顾问";
  }

  function setFallbackVisible(visible) {
    state.fallbackVisible = visible;
    if (!els.avatarFallback) {
      return;
    }

    els.avatarFallback.classList.toggle("visible", visible);
  }

  function setFallbackSpeaking(speaking) {
    if (!els.avatarFallback) {
      return;
    }

    els.avatarFallback.classList.toggle("speaking", speaking && state.fallbackVisible);
  }

  function showCaption(text) {
    if (!text) {
      els.speechCaption.hidden = true;
      els.speechCaption.textContent = "";
      return;
    }

    els.speechCaption.hidden = false;
    els.speechCaption.textContent = text;
  }

  function normalizeText(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function getFormValues() {
    return {
      country: els.targetCountry.value,
      degree: els.degreeLevel.value,
      major: normalizeText(els.majorTrack.value),
      intake: els.intakeSeason.value,
      budget: els.budgetLevel.value,
      profile: els.profileLevel.value,
      notes: normalizeText(els.studentNotes.value),
    };
  }

  function buildPlan(values) {
    const playbook = countryPlaybook[values.country] || countryPlaybook.英国;
    const major = values.major;
    const notes = values.notes;

    let scenario;
    if (/金融|商科|金融科技/.test(major)) {
      scenario = {
        label: "金融职业转化型申请",
        summary: "这类申请的重点不是把所有商科项目都铺开，而是先判断你更适合金融科技、资产管理、风险分析还是管理类金融。",
        positioning: "建议把券商、咨询、数据能力和职业目标串成一条清晰主线，让学校看到你不是泛泛申请商科，而是在为金融岗位做递进准备。",
        timeline: "先完成职业叙事和项目清单，再针对不同学校微调文书案例，实习经历要尽早整理成可量化成果。",
        schoolMix: "冲刺项目可以放在城市资源强、就业网络好的学校；主申项目优先选课程含金融科技、量化或实践模块的项目；保稳项目则看录取稳定性和毕业去向。",
        speech: "这类背景适合走金融职业转化路线。先把券商实习、咨询经历和金融科技兴趣串成一条职业主线，学校选择再按就业资源、课程实践和录取稳定性分层。",
        speechTail: "英国商科材料要尽早定文书主线。先把职业目标、实习证据和课程选择对齐，再处理推荐信沟通和首轮投递时间。",
        nextAction: "下一步先重写金融方向简历，把券商和咨询经历拆成市场研究、数据处理、客户问题和结果产出四类证据；个人陈述重点放在就业方向和项目课程匹配。",
      };
    } else if (/人工智能|计算机|AI|算法/.test(major)) {
      scenario = {
        label: "技术项目冲刺型申请",
        summary: "这类申请要先确认你是偏算法研究、工程落地还是跨学科 AI 应用，不同方向对应的项目池完全不同。",
        positioning: "你的核心竞争力应放在课程基础、算法实习、科研经历和项目产出上，文书要突出技术问题、解决路径和结果，而不是泛泛写兴趣。",
        timeline: "先把 GitHub、论文、项目报告或实习成果整理出来，再倒排推荐信和文书，不要等到最后才补技术材料。",
        schoolMix: "冲刺项目看实验室和方向匹配，主申项目看课程深度和就业出口，保稳项目则优先保证计算机主干课程要求能满足。",
        speech: "人工智能方向不能只看学校排名。算法实习、科研经历和项目成果是核心证据，先把技术能力讲清楚，再把冲刺、主申和保稳项目分开选择。",
        speechTail: "美国 AI 申请要把技术材料前置。项目报告、科研经历和推荐人方向先确定，再决定哪些学校冲实验室资源，哪些学校保课程和就业。",
        nextAction: "下一步先挑 2 到 3 个算法或科研项目，按问题、方法、工具、指标和结果重写；推荐信优先找能证明技术深度的人，而不是只追求头衔。",
      };
    } else if (/传媒|媒体|传播|新媒体/.test(major)) {
      scenario = {
        label: "跨专业叙事补强型申请",
        summary: "传媒申请最怕只说兴趣，关键是解释为什么从原专业转向传播，以及你已经用哪些经历验证了这个选择。",
        positioning: "建议把语言能力、校园媒体、品牌内容运营和目标方向连起来，形成内容策划、受众理解和传播执行的组合优势。",
        timeline: "先完成转专业动机和作品经历梳理，再补充作品集或内容案例，香港滚动录取节奏快，材料要尽早闭环。",
        schoolMix: "冲刺项目放在综合声誉和传播资源强的学校；主申项目看课程是否覆盖数字媒体、品牌传播或新闻传播；保稳项目重视录取节奏和作品要求。",
        speech: "跨专业申请传媒，关键是证明转向有依据。校园媒体、品牌内容运营和语言能力可以组成申请主线，文书里要解释清楚动机、作品和目标岗位。",
        speechTail: "香港传媒项目节奏快，最重要的是让转专业理由站得住。作品案例、内容运营数据和职业方向要先闭环，再赶第一批滚动录取。",
        nextAction: "下一步先整理 3 个内容作品或运营案例，写清楚选题、执行、渠道和反馈数据；文书重点解释为什么从英语背景转向新媒体传播。",
      };
    } else if (/商业分析|数据分析|统计/.test(major)) {
      scenario = {
        label: "数据商业结合型申请",
        summary: "商业分析申请要同时证明数据能力和商业理解，不能只写会工具，也不能只写商业兴趣。",
        positioning: "建议把统计背景、咨询实习和数据分析项目组合起来，突出你能把业务问题拆成指标、模型和决策建议。",
        timeline: "先整理数据项目和咨询案例，再筛选课程结构更贴近就业的项目，新加坡项目少而精，匹配度比广撒网更重要。",
        schoolMix: "冲刺项目看数据课程深度和行业连接；主申项目看 capstone、实习和就业资源；保稳项目看先修课要求和录取稳定性。",
        speech: "商业分析申请要同时证明数据能力和商业理解。统计基础负责支撑方法，咨询实习负责支撑业务判断，数据项目负责证明你能把问题落到结果上。",
        speechTail: "新加坡商业分析项目数量少，不能广撒网。先确认先修课和数据项目强度，再挑课程结构、行业连接和就业出口最匹配的项目。",
        nextAction: "下一步先把一个数据分析项目改成商业问题、数据来源、分析方法、结论建议四段；简历和文书都围绕这个案例证明业务转化能力。",
      };
    } else {
      scenario = {
        label: "综合定位型申请",
        summary: "这类申请要先把方向、预算和背景边界理清楚，再决定冲刺和保稳比例。",
        positioning: "建议以专业匹配、预算边界和结果回报三条线来判断，不要只看单一排名。",
        timeline: "先完成方向确认和材料盘点，再进入文书与投递节奏。",
        schoolMix: "冲刺、主申、保稳三层都要保留，避免结果过度集中在单一风险区间。",
        speech: "申请大学要先确定目标、预算和背景边界，再分出冲刺、主申和保稳学校。材料准备的重点，是用成绩、经历和动机证明你和目标项目匹配。",
        speechTail: "如果方向还没完全确定，先不要急着投递。先把可选国家、预算、成绩和经历放在一起比较，再决定最稳的申请组合。",
        nextAction: "下一步先整理简历、成绩单、语言成绩和关键经历，再根据目标国家的要求判断哪些材料需要补强。",
      };
    }

    const summary = `${scenario.label}。${scenario.summary} 当前目标是${values.country}${values.degree}的${major}方向，入学季为${values.intake}，预算区间是${values.budget}。`;
    const positioning = `${scenario.positioning} 结合当前背景“${values.profile}”，${playbook.tone}`;
    const timeline = `${scenario.timeline} ${playbook.timeline}`;
    const schoolMix = `${scenario.schoolMix} ${playbook.schools}`;
    const nextSteps = scenario.nextAction;
    const speech = `${scenario.speech} ${scenario.speechTail}`;

    return { summary, positioning, timeline, schoolMix, nextSteps, speech };
  }

  function renderPlan(plan) {
    state.lastPlan = plan;
    els.summaryText.textContent = plan.summary;
    els.planPositioning.textContent = plan.positioning;
    els.planTimeline.textContent = plan.timeline;
    els.planSchoolMix.textContent = plan.schoolMix;
    els.planNextSteps.textContent = plan.nextSteps;
  }

  async function connectAvatar({ autoplayIntro = true } = {}) {
    if (state.avatar) {
      return state.avatar;
    }

    if (!config.appId || !config.appSecret || !config.gatewayServer) {
      throw new Error("缺少 XMOV Web 配置，无法建立顾问会话。");
    }

    setStatus("connecting", "顾问接入中");
    log("Begin avatar connection");

    const headers = config.authHeader ? { Authorization: config.authHeader } : undefined;

    state.avatar = new window.XmovAvatar({
      containerId: "#avatarMount",
      appId: config.appId,
      appSecret: config.appSecret,
      headers,
      gatewayServer: config.gatewayServer,
      enableDebugger: false,
      enableLogger: true,
      config: PROFESSIONAL_AVATAR_CONFIG,
      onWidgetEvent(data) {
        log(`Widget: ${JSON.stringify(data)}`);
        if (data?.type === "subtitle_on") {
          showCaption(data.text || "");
        } else if (data?.type === "subtitle_off") {
          showCaption("");
        }
      },
      onNetworkInfo(info) {
        log(`Network: ${JSON.stringify(info)}`);
      },
      onMessage(message) {
        const payload = typeof message === "string" ? message : JSON.stringify(message);
        log(`SDK message: ${payload}`);
        if (message?.code && message.code !== 0) {
          state.errors.push(message);
        }
      },
      onStartSessionWarning(message) {
        const payload = typeof message === "string" ? message : JSON.stringify(message);
        state.errors.push(payload);
        log(`Start session warning: ${payload}`, "error");
      },
      onStateChange(status) {
        log(`State: ${status}`);
      },
      onStatusChange(status) {
        log(`Status: ${status}`);
      },
      onStateRenderChange(status, duration) {
        log(`Render: ${status}, duration=${duration}`);
      },
      onVoiceStateChange(status) {
        log(`Voice: ${status}`);
        setFallbackSpeaking(status === "start");
        if (status && String(status).includes("end")) {
          setFallbackSpeaking(false);
        }
      },
    });

    await state.avatar.init({
      onDownloadProgress(progress) {
        log(`Progress: ${progress}`);
      },
      initModel: "normal",
    });

    setConnected(true);
    setStatus("online", "顾问在线");
    setFallbackVisible(false);
    log("Avatar connected");

    if (autoplayIntro) {
      await speakText(
        "欢迎进入留学申请咨询台。先确认目标国家、专业方向、预算和当前背景，再判断申请定位、选校梯度和准备节奏。",
      );
    }

    return state.avatar;
  }

  async function disconnectAvatar() {
    if (!state.avatar) {
      return;
    }

    try {
      log("Destroy avatar session");
      await state.avatar.destroy();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      state.errors.push(message);
      log(`Destroy failed: ${message}`, "error");
    } finally {
      state.avatar = null;
      setConnected(false);
      setStatus("idle", "顾问未上线");
      showCaption("");
      setFallbackSpeaking(false);
      setFallbackVisible(false);
      log("Avatar disconnected");
    }
  }

  async function speakText(text) {
    if (!state.avatar) {
      throw new Error("顾问尚未连接。");
    }

    const content = normalizeText(text);
    if (!content) {
      return;
    }

    showCaption("");
    setFallbackSpeaking(true);
    log(`Speak: ${content}`);
    state.avatar.speak(content, true, true);
  }

  async function getAvatarAudioElement() {
    const startedAt = Date.now();

    while (Date.now() - startedAt < 15000) {
      const audioElement = state.avatar?.renderScheduler?.audioRenderer?.mseAudioPlayer?.audioElement;
      if (audioElement) {
        return audioElement;
      }

      await new Promise((resolve) => setTimeout(resolve, 200));
    }

    throw new Error("XMOV audio element not ready");
  }

  async function startPageAudioRecording() {
    if (state.audioRecording) {
      return;
    }

    if (!state.avatar) {
      throw new Error("Avatar is not connected");
    }

    const audioElement = await getAvatarAudioElement();
    const audioContext = new AudioContext({ sampleRate: 48000 });
    await audioContext.resume();

    const source = audioContext.createMediaElementSource(audioElement);
    const destination = audioContext.createMediaStreamDestination();
    source.connect(destination);
    source.connect(audioContext.destination);

    const chunks = [];
    const recorder = new MediaRecorder(destination.stream, {
      mimeType: "audio/webm;codecs=opus",
    });

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size) {
        chunks.push(event.data);
      }
    };

    recorder.start(250);
    state.audioRecording = { audioContext, chunks, recorder, source };
    log("Page audio recording started");
  }

  async function stopPageAudioRecording() {
    const session = state.audioRecording;
    if (!session) {
      return null;
    }

    await new Promise((resolve) => {
      session.recorder.onstop = resolve;
      session.recorder.stop();
    });

    const blob = new Blob(session.chunks, { type: "audio/webm" });
    await fetch("/api/recording-audio", {
      method: "POST",
      body: blob,
    });
    await session.audioContext.close();
    state.audioRecording = null;
    log("Page audio recording saved");
    return blob.size;
  }

  async function waitForSpeechStart(timeout = 15000) {
    const audioElement = await getAvatarAudioElement();
    const startedAt = Date.now();

    while (Date.now() - startedAt < timeout) {
      if (!audioElement.paused) {
        return;
      }

      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }

  async function waitForSpeechIdle(timeout = 60000) {
    const audioElement = await getAvatarAudioElement();
    const startedAt = Date.now();
    let sawPlayback = !audioElement.paused;

    while (Date.now() - startedAt < timeout) {
      if (!audioElement.paused) {
        sawPlayback = true;
      }

      if (sawPlayback && audioElement.paused) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        if (audioElement.paused) {
          return;
        }
      }

      await new Promise((resolve) => setTimeout(resolve, 150));
    }
  }

  async function speakAndWait(text) {
    await speakText(text);
    await waitForSpeechStart();
    await waitForSpeechIdle();
  }

  async function runRecordedDemo() {
    if (state.recordDemoStarted) {
      return;
    }

    state.recordDemoStarted = true;
    window.__studyBridgeRecordDemoDone = false;

    try {
      window.scrollTo({ top: 0, behavior: "instant" });
      await connectAvatar({ autoplayIntro: false });
      await startPageAudioRecording();

      await speakAndWait("进入申请咨询台后，第一步是确认目标国家、专业方向、预算和当前背景，再确定学校梯度和材料优先级。顾问建议不能只停留在一句概括，需要说明为什么这样定位、哪些经历最影响录取、文书应该围绕什么主线展开，以及下一步先准备哪几类材料。这样用户听完以后，能明确知道先改简历、补语言、沟通推荐信，还是先调整选校梯度。");

      applyPreset("us-ai");
      await handleGenerate();
      await waitForSpeechIdle();

      applyPreset("uk-finance");
      await handleGenerate();
      await waitForSpeechIdle();

      await speakAndWait("这份申请方案的重点已经明确：先定方向和学校梯度，再推进语言成绩、推荐信、简历和个人陈述。接下来不要同时处理所有材料，而是先把最能证明匹配度的经历整理出来，形成简历和文书共同使用的主线。然后根据目标国家的投递节奏倒排时间，确认哪些项目适合冲刺，哪些项目适合作为主申和保稳，避免临近截止日期才仓促修改材料。");
      await stopPageAudioRecording();
      window.__studyBridgeRecordDemoDone = true;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      state.errors.push(message);
      log(`Record demo failed: ${message}`, "error");
      try {
        await stopPageAudioRecording();
      } catch {}
      window.__studyBridgeRecordDemoDone = true;
    }
  }

  function applyPreset(key) {
    const preset = presets[key];
    if (!preset) {
      return;
    }

    els.targetCountry.value = preset.country;
    els.degreeLevel.value = preset.degree;
    els.majorTrack.value = preset.major;
    els.intakeSeason.value = preset.intake;
    els.budgetLevel.value = preset.budget;
    els.profileLevel.value = preset.profile;
    els.studentNotes.value = preset.notes;
    renderPlan(buildPlan(getFormValues()));
  }

  async function handleConnect() {
    try {
      await connectAvatar({ autoplayIntro: true });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      state.errors.push(message);
      setStatus("error", "连接失败");
      log(`Connect failed: ${message}`, "error");
    }
  }

  async function handleGenerate() {
    try {
      if (!state.connected) {
        await connectAvatar({ autoplayIntro: false });
      }

      const plan = buildPlan(getFormValues());
      renderPlan(plan);
      await speakText(plan.speech);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      state.errors.push(message);
      log(`Generate failed: ${message}`, "error");
    }
  }

  async function handleIntro() {
    try {
      if (!state.connected) {
        await connectAvatar({ autoplayIntro: false });
      }

      await speakText(
        "申请大学的第一步不是马上列学校，而是先确认目标、预算、背景和时间线，再决定冲刺、主申和保稳项目。",
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      state.errors.push(message);
      log(`Intro failed: ${message}`, "error");
    }
  }

  function bindEvents() {
    els.connectBtn.addEventListener("click", handleConnect);
    els.statusPill.addEventListener("click", () => {
      if (!state.connected && state.status !== "connecting") {
        handleConnect();
      }
    });
    els.generateBtn.addEventListener("click", handleGenerate);
    els.introBtn.addEventListener("click", handleIntro);

    els.quickPicks.forEach((button) => {
      button.addEventListener("click", () => {
        applyPreset(button.dataset.preset);
      });
    });

    window.addEventListener("beforeunload", () => {
      if (state.avatar) {
        disconnectAvatar();
      }
    });

    window.addEventListener("keydown", async (event) => {
      if (!event.ctrlKey || !event.altKey) {
        return;
      }

      try {
        if (event.key.toLowerCase() === "r") {
          await startPageAudioRecording();
        } else if (event.key.toLowerCase() === "s") {
          await stopPageAudioRecording();
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        state.errors.push(message);
        log(`Audio recording failed: ${message}`, "error");
      }
    });
  }

  function initPage() {
    setStatus("idle", "顾问未上线");
    setConnected(false);
    setFallbackVisible(true);
    bindEvents();
    renderPlan(buildPlan(getFormValues()));
    log("StudyBridge ready");

    if (new URLSearchParams(window.location.search).has("recordDemo")) {
      runRecordedDemo();
    }
  }

  initPage();
})();
