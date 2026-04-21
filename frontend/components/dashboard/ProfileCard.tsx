"use client";

/**
 * Account profile card with a view/edit toggle.
 *
 * View mode renders every field read-only so the Overview tab can
 * double as an at-a-glance account summary. Edit mode turns the
 * whitelisted subset into inputs and fires PATCH /auth/me; identity
 * fields (email / ID / auth provider / verification status / created
 * date) are never editable. On save we bubble the fresh User back up
 * so the layout's header also refreshes.
 */
import { useState } from "react";

import { ApiError, updateMe, type UpdateUserPayload, type User } from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";

export function ProfileCard({
  user,
  onUpdated,
}: {
  user: User;
  onUpdated: (u: User) => void;
}) {
  const [editing, setEditing] = useState(false);

  return editing ? (
    <ProfileEditForm
      user={user}
      onCancel={() => setEditing(false)}
      onSaved={(u) => {
        onUpdated(u);
        setEditing(false);
      }}
    />
  ) : (
    <ProfileView user={user} onEdit={() => setEditing(true)} />
  );
}

// ---------------------------------------------------------------------------
// View mode
// ---------------------------------------------------------------------------

function ProfileView({ user, onEdit }: { user: User; onEdit: () => void }) {
  const created = user.created_at
    ? new Date(user.created_at).toLocaleDateString()
    : "—";
  return (
    <section className="rounded-lg border border-sage-border bg-white p-5 shadow-sage">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-sage-tertiary">
          Profile
        </h2>
        <button
          onClick={onEdit}
          className="rounded-md border border-sage-border bg-white px-3 py-1 text-xs font-medium text-accent-deep hover:bg-[rgba(58,125,92,0.08)]"
        >
          Edit
        </button>
      </div>

      <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
        <Field label="Name" value={user.name} />
        <Field
          label="Email"
          value={
            <span className="inline-flex items-center gap-2">
              <span>{user.email}</span>
              {user.email_verified ? (
                <span className="rounded-full bg-[rgba(58,125,92,0.1)] px-2 py-0.5 text-xs font-medium text-accent-deep">
                  verified
                </span>
              ) : (
                <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
                  unverified
                </span>
              )}
            </span>
          }
          hint="Read-only"
        />
        <Field label="Institution" value={user.institution ?? "—"} />
        <Field label="Country" value={user.country ?? "—"} />
        <Field label="Research area" value={user.research_area ?? "—"} />
        <Field
          label="ORCID"
          value={
            user.orcid ? (
              <a
                href={`https://orcid.org/${user.orcid}`}
                target="_blank"
                rel="noreferrer"
                className="text-accent-deep hover:underline"
              >
                {user.orcid}
              </a>
            ) : (
              "—"
            )
          }
        />
        <Field label="Sign-in method" value={user.auth_provider} hint="Read-only" />
        <Field label="Member since" value={created} hint="Read-only" />
        <Field
          label="Bio"
          value={user.bio ? (
            <p className="whitespace-pre-wrap text-sage-ink">{user.bio}</p>
          ) : (
            "—"
          )}
          span={2}
        />
      </dl>
    </section>
  );
}

function Field({
  label,
  value,
  hint,
  span = 1,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  span?: 1 | 2;
}) {
  return (
    <div className={span === 2 ? "sm:col-span-2" : undefined}>
      <dt className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-sage-tertiary">
        {label}
        {hint ? (
          <span className="text-[10px] font-normal text-slate-400">({hint})</span>
        ) : null}
      </dt>
      <dd className="mt-0.5 text-sage-ink">{value}</dd>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Edit mode
// ---------------------------------------------------------------------------

function ProfileEditForm({
  user,
  onCancel,
  onSaved,
}: {
  user: User;
  onCancel: () => void;
  onSaved: (u: User) => void;
}) {
  const [form, setForm] = useState({
    name: user.name,
    institution: user.institution ?? "",
    country: user.country ?? "",
    research_area: user.research_area ?? "",
    bio: user.bio ?? "",
    orcid: user.orcid ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof typeof form>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    const token = loadToken();
    if (!token) return;
    setSaving(true);
    setError(null);
    // Convert empty strings back to null so the server clears the field
    // instead of storing whitespace.
    const payload: UpdateUserPayload = {
      name: form.name.trim() || user.name, // name can't actually clear
      institution: form.institution.trim() || null,
      country: form.country.trim() || null,
      research_area: form.research_area.trim() || null,
      bio: form.bio.trim() || null,
      orcid: form.orcid.trim() || null,
    };
    try {
      const updated = await updateMe(token, payload);
      onSaved(updated);
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.message : "Failed to save profile";
      setError(msg);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-lg border border-sage-border bg-white p-5 shadow-sage">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-sage-tertiary">
        Edit profile
      </h2>
      <form onSubmit={onSave} className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Input
          label="Name"
          value={form.name}
          onChange={(v) => set("name", v)}
          required
          minLength={2}
        />
        <Input
          label="Institution"
          value={form.institution}
          onChange={(v) => set("institution", v)}
        />
        <Input
          label="Country"
          value={form.country}
          onChange={(v) => set("country", v)}
        />
        <Input
          label="Research area"
          value={form.research_area}
          onChange={(v) => set("research_area", v)}
          placeholder="e.g. high-Tc cuprates"
        />
        <Input
          label="ORCID"
          value={form.orcid}
          onChange={(v) => set("orcid", v)}
          placeholder="0000-0002-1825-0097"
          span={2}
        />
        <div className="sm:col-span-2">
          <label className="block">
            <span className="text-xs font-medium uppercase tracking-wide text-sage-tertiary">
              Bio
            </span>
            <textarea
              className="mt-1 block w-full rounded-md border border-sage-border px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              rows={4}
              maxLength={2000}
              value={form.bio}
              onChange={(e) => set("bio", e.target.value)}
              placeholder="A short note about your research interests (visible only to you for now)."
            />
          </label>
          <p className="mt-1 text-xs text-sage-tertiary">
            {form.bio.length} / 2000
          </p>
        </div>
        {error && (
          <p className="sm:col-span-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}
        <div className="flex gap-2 sm:col-span-2">
          <button
            type="submit"
            disabled={saving}
            className="rounded-md bg-accent-deep px-4 py-2 text-sm font-medium text-white hover:bg-accent disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="rounded-md border border-sage-border bg-white px-4 py-2 text-sm text-sage-muted hover:text-accent-deep"
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

function Input({
  label,
  value,
  onChange,
  placeholder,
  required,
  minLength,
  span = 1,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
  minLength?: number;
  span?: 1 | 2;
}) {
  return (
    <label className={`block ${span === 2 ? "sm:col-span-2" : ""}`}>
      <span className="text-xs font-medium uppercase tracking-wide text-sage-tertiary">
        {label}
      </span>
      <input
        className="mt-1 block w-full rounded-md border border-sage-border px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        minLength={minLength}
      />
    </label>
  );
}
