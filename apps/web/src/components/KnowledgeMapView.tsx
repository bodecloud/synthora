import { KnowledgeEdge, KnowledgeNode } from "../api";

function NodeTree({
  node,
  byParent,
}: {
  node: KnowledgeNode;
  byParent: Map<string | null, KnowledgeNode[]>;
}) {
  const children = byParent.get(node.id) ?? [];
  return (
    <div className="kmap-node">
      <div className="kmap-label">
        {node.name}
        {node.infos.length > 0 && (
          <span className="kmap-count">{node.infos.length} sources</span>
        )}
      </div>
      {children.map((c) => (
        <NodeTree key={c.id} node={c} byParent={byParent} />
      ))}
    </div>
  );
}

export function KnowledgeMapView({
  nodes,
  edges = [],
}: {
  nodes: KnowledgeNode[];
  edges?: KnowledgeEdge[];
}) {
  const byParent = new Map<string | null, KnowledgeNode[]>();
  for (const n of nodes) {
    const list = byParent.get(n.parent_id) ?? [];
    list.push(n);
    byParent.set(n.parent_id, list);
  }
  const roots = byParent.get(null) ?? [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return (
    <div>
      {roots.map((r) => (
        <NodeTree key={r.id} node={r} byParent={byParent} />
      ))}
      {edges.length > 0 && (
        <details style={{ marginTop: "0.75rem" }}>
          <summary>{edges.length} relations</summary>
          <ul className="kmap-edges">
            {edges.map((e) => (
              <li key={e.id}>
                <code>{byId.get(e.source_id)?.name ?? e.source_id}</code>
                {" — "}
                <em>{e.relation}</em>
                {" → "}
                <code>{byId.get(e.target_id)?.name ?? e.target_id}</code>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
