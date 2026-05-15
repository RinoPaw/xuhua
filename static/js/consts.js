export const humanVideos = {
  idle: ["/static/media/wait1.mp4", "/static/media/wait2.mp4"],
  thinking: ["/static/media/greet1.mp4"],
  speaking: ["/static/media/speak1.mp4", "/static/media/speak2.mp4", "/static/media/speak3.mp4"],
  farewell: ["/static/media/thanksandbye.mp4"],
};
export const humanVideoIndexes = {};

export const suggestionQueryPool = [
  "汴绣是什么？",
  "朱仙镇木版年画有什么特点？",
  "罗山皮影戏和桐柏皮影戏有什么区别？",
  "河南有哪些传统美术类非遗？",
  "哪些河南非遗适合做校园展示？",
  "推荐适合社区活动展示的河南非遗项目",
  "策划一个适合社区活动展示的河南非遗小展",
  "给朱仙镇木版年画生成讲解词",
  "给汴绣生成中英双语介绍",
  "围绕陈氏太极拳设计一个 15 分钟研学任务",
  "围绕豫剧设计一个适合中学生的研学任务",
  "把淮阳泥泥狗改写成更年轻化的版本",
  "把汴绣改成适合短视频口播的版本",
  "给太极拳写一段适合展板展示的简介",
  "推荐几个适合亲子互动体验的河南非遗项目",
  "给豫剧生成一段双语介绍",
  "比较一下汴绣和苏绣的风格差异",
  "策划一个以年画为主题的非遗互动角",
];

export function pickSuggestionQueries(count = 6) {
  const pool = [...suggestionQueryPool];
  for (let i = pool.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  return pool.slice(0, Math.max(0, Math.min(count, pool.length)));
}
export const followupQueriesByTask = {
  fact_qa: [
    "这个项目更适合校园展示还是社区活动？",
    "它和同类非遗有什么区别？",
    "帮我把它改成适合讲解的口语版",
  ],
  browse_query: [
    "从这些项目里推荐 3 个适合校园展示的",
    "把这些项目按展示难度做个比较",
    "帮我从中挑适合社区活动的项目",
  ],
  comparison: [
    "把这两个项目整理成展板讲解词",
    "推荐更适合校园展示的那个",
    "再加入一个同类项目一起比较",
  ],
  recommendation: [
    "基于这些推荐生成校园展示策划",
    "给每个推荐项目写一句推荐理由",
    "把推荐结果改成适合播报的讲解词",
  ],
  exhibition_plan: [
    "把这个方案压缩成 3 分钟讲解流程",
    "继续生成互动问题和研学任务",
    "改成适合社区活动的版本",
  ],
  study_task: [
    "再补 3 个课堂互动问题",
    "改成适合小学生的版本",
    "把这份任务单压缩成 15 分钟活动",
  ],
  content_transform: [
    "再生成一个更年轻化的版本",
    "改成双语传播文案",
    "基于这个项目再推荐几个相关非遗",
  ],
  chitchat: [
    "推荐适合校园展示的河南非遗项目",
    "四川皮影和湖北皮影有什么区别？",
    "河南有哪些传统美术类非遗？",
  ],
};

export const browserSpeechSupported = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
export const audioSpeechSupported = typeof Audio !== "undefined";
export const speechSupported = browserSpeechSupported || audioSpeechSupported;
export const PROGRESS_STEP_INDEX = {
  classify: 0,
  search: 1,
  generate: 2,
};
export const loadingSteps = [
  { title: "理解需求", label: "理解", detail: "识别问题意图、项目名称和上下文指向" },
  { title: "查找资料", label: "检索", detail: "先筛候选标题，必要时精查项目详情" },
  { title: "组织回答", label: "生成", detail: "整理依据，生成可直接使用的回答" },
];
export const HUMAN_MIN_THINKING_MS = 1120;
export const HUMAN_DISSOLVE_LEAD_MS = 1050;
export const LOADING_MIN_STEP_MS = 500;
