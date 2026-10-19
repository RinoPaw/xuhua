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
        {item?.case_id ? `${item.risk_level || "风险未标注"} · ${item.category || "类别未注明"}` : `${item?.level || "级别未注明"} · ${item?.category || "类别未注明"} · ${formatRegion(item)}`}
      </div>
      <p>{item?.summary || "资料库暂未提供项目简介。"}</p>
    </button>
  );
}

export function ItemDetail({ item, loading, error, onBack }) {
  const isCase = Boolean(item?.case_id);
  const sections = (isCase ? [
    ["案例摘要", item?.summary], ["案例性质", item?.nature_judgment],
    ["判断依据", item?.judgment_reason], ["关键手法", item?.key_methods?.join("、")],
    ["风险信号", item?.risk_signals], ["防范与处置建议", item?.prevention_advice],
    ["受害人群", item?.victim_group], ["入口渠道", item?.entry_channels?.join("、")],
    ["损失情况", [item?.loss_occurred, item?.loss_type?.join("、")].filter(Boolean).join(" · ")],
    ["资料来源", item?.source_name], ["发布日期", item?.publish_date],
  ] : [
    ["项目介绍", item?.content || item?.summary],
    ["历史沿革", item?.history],
    ["艺术特色", item?.features],
    ["文化价值", item?.cultural_value],
  ]).filter(([, value]) => value);

  return (
    <div className="item-detail">
      <div className="detail-top">
        <button type="button" onClick={onBack}><ArrowLeft />{isCase ? "返回案例" : "返回项目"}</button>
      </div>
      <div className="detail-scroll">
        <span className="detail-kicker">{isCase ? item.risk_level || "反诈案例" : item?.level || "非遗项目"}</span>
        <h2>{item?.title || "未命名项目"}</h2>
        <div className="detail-tags">
          <span>{item?.category || "类别未注明"}</span>
          {!isCase && <span>{formatRegion(item)}</span>}
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
        {!loading && isCase && item?.source_links?.filter(url => /^https?:\/\//iu.test(url)).map(url => (
          <p key={url}><a href={url} target="_blank" rel="noreferrer">查看来源原文</a></p>
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
