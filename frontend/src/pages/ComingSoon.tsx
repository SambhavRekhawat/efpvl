import { Link } from "react-router-dom";
import { PageHead } from "../components/Layout";

/** Honest placeholder: says what will live here and offers the useful detour. */
export default function ComingSoon(props: {
  eyebrow: string;
  title: string;
  phase: string;
  description: string;
}) {
  return (
    <div>
      <PageHead eyebrow={props.eyebrow} title={props.title} />
      <div className="empty">
        <p style={{ fontWeight: 600, color: "var(--text)" }}>
          Arrives in {props.phase}
        </p>
        <p className="small" style={{ marginTop: 6, maxWidth: "52ch", marginInline: "auto" }}>
          {props.description}
        </p>
        <p className="small" style={{ marginTop: 14 }}>
          Until then, the{" "}
          <Link to="/valuation">Valuation page</Link> already shows a sensitivity
          preview and the full calculation trace for every product.
        </p>
      </div>
    </div>
  );
}
