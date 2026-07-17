import { KnowledgeNode } from "../api";

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

export function KnowledgeMapView({ nodes }: { nodes: KnowledgeNode[] }) {
  const byParent = new Map<string | null, KnowledgeNode[]>();
  for (const n of nodes) {
    const list = byParent.get(n.parent_id) ?? [];
    list.push(n);
    byParent.set(n.parent_id, list);
  }
  const roots = byParent.get(null) ?? [];
  return (
    <div>
      {roots.map((r) => (
        <NodeTree key={r.id} node={r} byParent={byParent} />
      ))}
    </div>
  );
}
