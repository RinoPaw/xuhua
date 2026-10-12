import test from "node:test";
import assert from "node:assert/strict";
import { MIN_EARLY_CJK_CHARS, TtsTextPlan } from "../src/lib/ttsTextPlan.js";

test("commits exactly one first sentence and one complete remainder", () => {
  const plan = new TtsTextPlan();
  assert.equal(plan.append("第一句。第二"), null);
  assert.equal(plan.append("句。第三句。尾"), "第一句。第二句。");
  assert.equal(plan.append("巴。"), null);
  assert.equal(plan.finish(), "第三句。尾巴。");
  assert.equal(plan.finish(), null);
  assert.equal(plan.append("迟到文本。"), null);
});

test("commits a long CJK clause at a soft boundary before sentence completion", () => {
  const plan = new TtsTextPlan("zh-CN");
  const prefix = "如果你第一次认真看一幅传统汴绣作品，";
  assert.ok([...prefix.replace(/\s/gu, "")].length >= MIN_EARLY_CJK_CHARS);
  assert.equal(plan.append(`${prefix}可以先留意针脚的方向`), prefix);
  assert.equal(plan.append("和颜色层次。后面还有一句。"), null);
  assert.equal(plan.finish(), "可以先留意针脚的方向和颜色层次。后面还有一句。");
});

test("does not commit a short CJK clause just because a comma arrived", () => {
  const plan = new TtsTextPlan("zh-CN");
  assert.equal(plan.append("汴绣很特别，尤其是它的层次感"), null);
  assert.equal(plan.append("。"), "汴绣很特别，尤其是它的层次感。");
  assert.equal(plan.finish(), null);
});

test("uses the whole answer as the only segment when no early boundary arrives", () => {
  const plan = new TtsTextPlan();
  assert.equal(plan.append("没有标点的回答"), null);
  assert.equal(plan.finish(), "没有标点的回答");
});

test("commits an English full stop without using comma as an early boundary", () => {
  const plan = new TtsTextPlan("en-US");
  assert.equal(plan.append("This clause is already quite long, but still incomplete"), null);
  assert.equal(plan.append(". The sec"), "This clause is already quite long, but still incomplete.");
  assert.equal(plan.append("ond sentence. A third sentence."), null);
  assert.equal(plan.finish(), "The second sentence. A third sentence.");
});

test("does not split decimals, common abbreviations, or initialisms", () => {
  const plan = new TtsTextPlan("en-US");
  assert.equal(
    plan.append("The value is 3.14 and Dr. Zhang used e.g. paper cutting. Next."),
    "The value is 3.14 and Dr. Zhang used e.g. paper cutting.",
  );
  assert.equal(plan.finish(), "Next.");
});

test("keeps a closing quote with the completed English sentence", () => {
  const plan = new TtsTextPlan("en-US");
  assert.equal(plan.append('She said “Hello.” Then left.'), 'She said “Hello.”');
  assert.equal(plan.finish(), "Then left.");
});


test("an eight-character Chinese clause starts TTS before sentence completion", () => {
  const plan = new TtsTextPlan("zh-CN");
  const prefix = "这项技艺历史悠久，";
  assert.ok([...prefix].length >= MIN_EARLY_CJK_CHARS);
  assert.equal(plan.append("这项技艺"), null);
  assert.equal(plan.append("历史悠久，"), prefix);
  assert.equal(plan.append("有着非常独特的传承背景。"), null);
  assert.equal(plan.finish(), "有着非常独特的传承背景。");
});

test("short pauses still wait for a meaningful phrase rather than generating tiny audio clips", () => {
  const plan = new TtsTextPlan("zh-CN");
  assert.equal(plan.append("你好，"), null);
  assert.equal(plan.append("朋友，"), null);
  assert.equal(plan.append("今天介绍木版年画。"), "你好，朋友，今天介绍木版年画。");
  assert.equal(plan.finish(), null);
});


test("three-character Chinese first sentence is combined with subsequent speech", () => {
  const plan = new TtsTextPlan("zh-CN");
  assert.equal(plan.append("你好。"), null);
  assert.equal(plan.append("今天来介绍豫剧。"), "你好。今天来介绍豫剧。");
  assert.equal(plan.finish(), null);
});

test("multiple tiny completed sentences keep original order and all punctuation", () => {
  const plan = new TtsTextPlan("zh-CN");
  const parts = ["是的。", "我在。", "可以。", "我们开始。", "后面还有一段。"];
  const early = [];
  for (const part of parts) {
    const segment = plan.append(part);
    if (segment) early.push(segment);
  }
  const final = plan.finish();
  assert.equal([...early, final].filter(Boolean).join(""), parts.join(""));
  assert.equal(early.length, 1);
  assert.equal(early[0], "是的。我在。");
});

test("a single short reply still plays in full after the turn completes", () => {
  const plan = new TtsTextPlan("zh-CN");
  assert.equal(plan.append("好的。"), null);
  assert.equal(plan.finish(), "好的。");
  assert.equal(plan.finish(), null);
});

test("a normal six-character Chinese sentence still starts TTS early", () => {
  const plan = new TtsTextPlan("zh-CN");
  assert.equal(plan.append("这里非常美。后面继续"), "这里非常美。");
  assert.equal(plan.finish(), "后面继续");
});
