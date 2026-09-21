import { ArrowLeft, CaretRight, SpinnerGap } from "@phosphor-icons/react";

import { Markdown } from "./ConversationMessage.jsx";

function formatRegion(item) {
  return [item?.province, item?.city, item?.district].filter(Boolean).join(" · ") || "地区未注明";
}

export function SourceItem({ item, onOpen }) {
  return (
    <button type="button" className="source-item" onClick={() => onOpen(item)}>
      <div className="source-title"><h3>{item?.title || "未命名项目"}</h3><CaretRight /></div>
      <div className="source-meta">
        {item?.level || "级别未注明"} · {item?.category || "类别未注明"} · {formatRegion(item)}
      </div>
      <p>{item?.summary || "资料库暂未提供项目简介。"}</p>
    </button>
  );
}

export function ItemDetail({ item, loading, error, onBack }) {
  const sections = [
    ["项目介绍", item?.content || item?.summary],
    ["历史沿革", item?.history],
    ["艺术特色", item?.features],
    ["文化价值", item?.cultural_value],
  ].filter(([, value]) => value);

  return (
    <div className="item-detail">
      <div className="detail-top">
        <button type="button" onClick={onBack}><ArrowLeft />返回项目</button>
      </div>
      <div className="detail-scroll">
        <span className="detail-kicker">{item?.level || "非遗项目"}</span>
        <h2>{item?.title || "未命名项目"}</h2>
        <div className="detail-tags">
          <span>{item?.category || "类别未注明"}</span>
          <span>{formatRegion(item)}</span>
        </div>
        {loading && (
          <div className="detail-loading">
            <SpinnerGap className="spin" />正在读取完整资料
          </div>
        )}
        {error && <div className="search-error" role="alert">{error}</div>}
        {!loading && sections.map(([title, content]) => (
          <section key={title}>
            <h3>{title}</h3>
            <Markdown text={content} className="detail-markdown" />
          </section>
        ))}
        {!loading && item?.display_forms?.length > 0 && (
          <section>
            <h3>呈现形式</h3>
            <div className="detail-pills">
              {item.display_forms.map((value) => <span key={value}>{value}</span>)}
            </div>
          </section>
        )}
        {!loading && item?.suitable_scenarios?.length > 0 && (
          <section>
            <h3>适合场景</h3>
            <div className="detail-pills">
              {item.suitable_scenarios.map((value) => <span key={value}>{value}</span>)}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
