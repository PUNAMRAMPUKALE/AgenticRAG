import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: string | null };

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error: error.message || String(error) };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="gate">
          <h1>UI crashed</h1>
          <p className="gate-error">{this.state.error}</p>
          <p>Hard-refresh http://127.0.0.1:5173 (Ctrl+Shift+R).</p>
        </div>
      );
    }
    return this.props.children;
  }
}
