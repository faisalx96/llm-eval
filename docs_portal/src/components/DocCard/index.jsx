import React from "react";
import Link from "@docusaurus/Link";

export default function DocCard({ title, href, eyebrow, children }) {
  return (
    <Link className="doc-card" to={href}>
      {eyebrow ? <div className="doc-card-eyebrow">{eyebrow}</div> : null}
      <div className="doc-card-title">{title}</div>
      <div className="doc-card-body">{children}</div>
    </Link>
  );
}
