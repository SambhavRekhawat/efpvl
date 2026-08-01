import katex from "katex";
import "katex/dist/katex.min.css";
import { useMemo } from "react";

/** Renders a LaTeX string as proper mathematics (display or inline). */
export function Formula(props: { latex: string; display?: boolean }) {
  const html = useMemo(
    () =>
      katex.renderToString(props.latex, {
        displayMode: props.display ?? false,
        throwOnError: false,
        output: "html",
      }),
    [props.latex, props.display]
  );
  return (
    <span
      className={props.display ? "formula-block" : "formula-inline"}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
