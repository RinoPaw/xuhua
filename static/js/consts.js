export const humanVideos = {
  idle: ["/static/media/wait1.mp4", "/static/media/wait2.mp4"],
  thinking: ["/static/media/greet1.mp4"],
  speaking: ["/static/media/speak1.mp4", "/static/media/speak2.mp4", "/static/media/speak3.mp4"],
  farewell: ["/static/media/thanksandbye.mp4"],
};
export const humanVideoIndexes = {};

export const defaultSuggestionQueries = [
  "汴绣是什么？",
  "河南有哪些传统美术类非遗？",
  "四川皮影和湖北皮影有什么区别？",
  "推荐适合校园展示的河南非遗项目",
  "给朱仙镇木版年画生成讲解词",
  "适合社区活动展示的非遗有哪些？",
];
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
  { title: "理解问题", detail: "正在判断任务类型，并识别项目名称、地区和输出要求" },
  { title: "检索资料", detail: "正在检索资料库，优先匹配明确标题和结构化字段" },
  { title: "思考回答", detail: "正在整理证据、取舍资料，并生成回答文本" },
];
export const HUMAN_MIN_THINKING_MS = 1120;
export const HUMAN_DISSOLVE_LEAD_MS = 1050;
export const LOADING_MIN_STEP_MS = 500;
