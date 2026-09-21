import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CaretRight } from "@phosphor-icons/react";

import { rotateAndLimit } from "../lib/conversationState.js";

function formatRegion(item) {
  return [item?.province, item?.city, item?.district].filter(Boolean).join(" · ") || "地区未注明";
}

export function Markdown({ text, status, className = "" }) {
  if (!text) {
    const copy = status === "cancelled"
      ? "已停止回答"
      : status === "error"
        ? "没有完成回答"
        : "正在回答…";
    return <span className="muted-copy">{copy}</span>;
  }
  return (
    <div className={`markdown ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{String(text)}</ReactMarkdown>
    </div>
  );
}

function isCompactMessage(message) {
  const text = String(message?.content || "").trim();
  if (!text || message?.status !== "complete" || text.includes("\n") || text.length > 72) {
    return false;
  }
  return !/[#*_>`|\[\]]/.test(text);
}

function CitationCards({ sources, onOpen }) {
  if (!sources?.length) return null;
  return (
    <div className="citation-group" aria-label={`本轮引用 ${sources.length} 项资料`}>
      <div className="citation-heading">资料引用 · {sources.length}</div>
      <div className="citation-cards">
        {sources.map((item) => (
          <button key={item.id} type="button" className="citation-card" onClick={() => onOpen(item)}>
            <span className="citation-title">{item.title || "未命名项目"}</span>
            <span className="citation-meta">{item.level || "级别未注明"} · {formatRegion(item)}</span>
            <CaretRight aria-hidden="true" />
          </button>
        ))}
      </div>
    </div>
  );
}

export function PromptChips({ prompts, onAsk, className = "", rotationSeed = 0 }) {
  const visiblePrompts = useMemo(
    () => rotateAndLimit(prompts, rotationSeed),
    [prompts, rotationSeed],
  );
  if (!visiblePrompts.length) return null;
  return (
    <div className={`prompt-chips ${className}`}>
      {visiblePrompts.map((prompt) => (
        <button key={prompt} type="button" onClick={() => void onAsk(prompt)}>{prompt}</button>
      ))}
    </div>
  );
}

export function ConversationMessage({ message, onOpen, onAsk, rotationSeed = 0 }) {
  const compact = isCompactMessage(message);
  return (
    <article className={`message-row ${message.role}`}>
      {message.role === "assistant" && <span className="chat-avatar">叙</span>}
      <div className="message-content">
        {message.role === "assistant" && <span className="message-author">叙华</span>}
        <div className={`message-bubble ${compact ? "compact" : ""}`}>
          <Markdown text={message.content} status={message.status} />
        </div>
        <CitationCards sources={message.sources} onOpen={onOpen} />
        {message.role === "assistant" && (
          <PromptChips
            prompts={message.suggestions}
            rotationSeed={rotationSeed}
            onAsk={onAsk}
          />
        )}
      </div>
    </article>
  );
}
