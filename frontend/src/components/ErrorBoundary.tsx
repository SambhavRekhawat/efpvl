import { Component, ReactNode } from "react";

/**
 * Last line of defence: a rendering crash should degrade to a readable
 * message with a way out, never a blank white page.
 */
export default class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page">
        <div className="card">
          <h2>Something broke on this page</h2>
          <p className="small muted" style={{ margin: "8px 0 14px" }}>
            The valuation engine is unaffected — this is a display error.
            Reloading usually clears it.
          </p>
          <p className="mono small" style={{ color: "var(--faint)" }}>
            {this.state.error.message}
          </p>
          <button
            className="primary"
            style={{ marginTop: 14 }}
            onClick={() => window.location.assign("/")}
          >
            Return to Home
          </button>
        </div>
      </div>
    );
  }
}
