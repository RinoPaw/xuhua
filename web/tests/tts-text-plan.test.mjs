import test from "node:test";
import assert from "node:assert/strict";
import { MIN_EARLY_CJK_CHARS, TtsTextPlan } from "../src/lib/ttsTextPlan.js";

test("commits exactly one first sentence and one complete remainder", () => {
  const plan = new TtsTextPlan();
  assert.equal(plan.append("第一句。第二"), "第一句。");
  assert.equal(plan.append("句。第三句。尾"), null);
  assert.equal(plan.append("巴。"), null);
  assert.equal(plan.finish(), "第二句。第三句。尾巴。");
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
