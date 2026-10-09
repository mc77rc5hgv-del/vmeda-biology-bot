import { Component, type ReactNode } from "react";

/** A rendering failure must leave a way back into the app, without clearing data. */
export class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main role="alert" style={{ minHeight: "var(--tg-viewport-height, 100dvh)", display: "grid", placeItems: "center", padding: 24, background: "var(--background)", color: "var(--ink)" }}>
        <div style={{ maxWidth: 360, textAlign: "center" }}>
          <h1 style={{ fontSize: 20 }}>Не удалось показать страницу</h1>
          <p style={{ marginTop: 12, lineHeight: 1.5, color: "var(--ink-secondary)" }}>Попробуй открыть приложение ещё раз. Если ошибка повторяется, сообщи администрации.</p>
          <button type="button" onClick={() => window.location.reload()} style={{ marginTop: 20, minHeight: 44, padding: "12px 20px", borderRadius: 14, border: "1px solid var(--border)", background: "var(--surface-elevated)", color: "var(--ink)", font: "inherit", cursor: "pointer" }}>Открыть заново</button>
        </div>
      </main>
    );
  }
}
