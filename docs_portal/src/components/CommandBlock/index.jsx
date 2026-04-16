import React from "react";

export default function CommandBlock({ title, command, result }) {
  return (
    <div className="command-block">
      <div className="command-block-title">{title}</div>
      <pre>
        <code>{command}</code>
      </pre>
      {result ? <p className="command-block-result">{result}</p> : null}
    </div>
  );
}
