import { useEffect, useMemo, useState } from "react";
import { FieldRow, Notice, SchemaFields } from "../components/Forms";
import { api } from "../lib/api";
import { when } from "../lib/format";
import { describeParams, fieldsFromSchema, initialValues, parseValues, type FormValues } from "../lib/schemaForm";
import type { Strategy, StrategyType } from "../lib/types";
import { useStrategies } from "../lib/useStrategies";

type Editing = { mode: "new" } | { mode: "edit"; strategy: Strategy };

export default function Strategies() {
  const [showArchived, setShowArchived] = useState(false);
  const { strategies, types, error: loadError, reload } = useStrategies(showArchived);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const typeByName = useMemo(() => new Map((types ?? []).map((t) => [t.name, t])), [types]);

  const selectedId = editing?.mode === "edit" ? editing.strategy.strategy_id : null;

  return (
    <div className="page">
      <header className="page-head">
        <h1>Strategies</h1>
        <p className="lede">A strategy decides, after each scoring throw, whether a bot banks its points or throws again. Editing one saves a new version; results keep the version they used.</p>
      </header>
      {loadError && <Notice>{loadError}</Notice>}
      {message && <Notice kind="info">{message}</Notice>}
      <div className="two-col">
        <section aria-label="Library">
          <div className="list-head">
            <button className="primary" onClick={() => { setEditing({ mode: "new" }); setMessage(null); }}>New strategy</button>
            <label className="check">
              <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
              Show archived
            </label>
          </div>
          <ul className="library">
            {(strategies ?? []).map((s) => {
              const t = typeByName.get(s.type);
              const fields = t ? fieldsFromSchema(t.schema) : [];
              return (
                <li key={s.strategy_id} className={`${selectedId === s.strategy_id ? "selected" : ""} ${s.archived ? "archived" : ""}`}>
                  <button className="library-item" onClick={() => { setEditing({ mode: "edit", strategy: s }); setMessage(null); }}
                    aria-pressed={selectedId === s.strategy_id}>
                    <span className="li-name">{s.name}{s.archived && <span className="tag">archived</span>}</span>
                    <span className="li-type">{t?.title ?? s.type}{s.version > 1 ? `, version ${s.version}` : ""}</span>
                    <span className="li-params sub">{describeParams(fields, s.params)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
        <section aria-label="Editor">
          {editing && types ? (
            <Editor
              key={editing.mode === "edit" ? editing.strategy.strategy_version_id : "new"}
              editing={editing}
              types={types}
              onSaved={async (s, msg) => {
                await reload();
                setEditing({ mode: "edit", strategy: s });
                setMessage(msg);
              }}
              onRemoved={async (msg) => {
                await reload();
                setEditing(null);
                setMessage(msg);
              }}
            />
          ) : (
            <div className="empty"><p>Choose a strategy to see or edit it, or make a new one.</p></div>
          )}
        </section>
      </div>
    </div>
  );
}

function Editor({ editing, types, onSaved, onRemoved }: {
  editing: Editing;
  types: StrategyType[];
  onSaved: (s: Strategy, message: string) => void;
  onRemoved: (message: string) => void;
}) {
  const existing = editing.mode === "edit" ? editing.strategy : null;
  const [typeName, setTypeName] = useState(existing?.type ?? types[0].name);
  const type = types.find((t) => t.name === typeName)!;
  const fields = useMemo(() => fieldsFromSchema(type.schema), [type]);
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [values, setValues] = useState<FormValues>(() => initialValues(fields, existing?.params));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [versions, setVersions] = useState<Strategy[]>([]);

  useEffect(() => {
    if (existing) api.strategyVersions(existing.strategy_id).then((v) => setVersions(v.versions.reverse())).catch(() => undefined);
  }, [existing]);

  const changeType = (t: string) => {
    setTypeName(t);
    setValues(initialValues(fieldsFromSchema(types.find((x) => x.name === t)!.schema)));
    setErrors({});
  };

  const save = async () => {
    setError(null);
    const parsed = parseValues(fields, values);
    setErrors(parsed.errors);
    if (!name.trim()) {
      setError("Give the strategy a name.");
      return;
    }
    if (Object.keys(parsed.errors).length) return;
    try {
      if (existing) {
        const s = await api.updateStrategy(existing.strategy_id, { name: name.trim(), description, params: parsed.params });
        onSaved(s, s.version === existing.version ? "Nothing changed." : `Saved as version ${s.version}.`);
      } else {
        const s = await api.createStrategy({ name: name.trim(), description, type: typeName, params: parsed.params });
        onSaved(s, `${s.name} added.`);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = async () => {
    if (!existing) return;
    try {
      const r = await api.deleteStrategy(existing.strategy_id);
      onRemoved(r.result === "deleted"
        ? `${existing.name} deleted.`
        : `${existing.name} archived. Stored results use it, so its versions are kept; turn on "Show archived" to restore it.`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const restore = async () => {
    if (!existing) return;
    try {
      await api.restoreStrategy(existing.strategy_id);
      onSaved({ ...existing, archived: false }, `${existing.name} restored.`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <form className="editor" noValidate onSubmit={(e) => { e.preventDefault(); save(); }}>
      <h2>{existing ? existing.name : "New strategy"}</h2>
      <FieldRow label="Name" htmlFor="st-name">
        <input id="st-name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
      </FieldRow>
      <FieldRow label="Type" htmlFor="st-type" help={existing ? `${type.description} The type of a saved strategy cannot change.` : type.description}>
        <select id="st-type" value={typeName} disabled={!!existing} onChange={(e) => changeType(e.target.value)}>
          {types.map((t) => <option key={t.name} value={t.name}>{t.title}</option>)}
        </select>
      </FieldRow>
      <SchemaFields fields={fields} values={values} errors={errors} onChange={setValues} />
      <FieldRow label="Description" htmlFor="st-desc" help="Optional notes">
        <textarea id="st-desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
      </FieldRow>
      {error && <Notice>{error}</Notice>}
      <div className="actions">
        <button type="submit" className="primary">{existing ? "Save new version" : "Add strategy"}</button>
        {existing && !existing.archived && (
          <button type="button" className="quiet danger" onClick={remove}>
            {existing.has_results ? "Archive" : "Delete"}
          </button>
        )}
        {existing?.archived && <button type="button" onClick={restore}>Restore</button>}
      </div>
      {versions.length > 1 && (
        <section className="versions">
          <h3>Versions</h3>
          <ol reversed>
            {versions.map((v) => (
              <li key={v.strategy_version_id}>
                <span>Version {v.version}</span>
                <span className="sub">{when(v.created_at)}</span>
                <span className="sub">{describeParams(fields, v.params)}</span>
              </li>
            ))}
          </ol>
        </section>
      )}
    </form>
  );
}
