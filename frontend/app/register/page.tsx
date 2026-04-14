"use client";

import Link from "next/link";
import { useState } from "react";
import { register, ApiError } from "@/lib/api";

export default function RegisterPage() {
  const [form, setForm] = useState({
    email: "",
    password: "",
    name: "",
    age: "",
    institution: "",
    country: "",
    research_area: "",
    purpose: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  function update<K extends keyof typeof form>(k: K, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await register({
        email: form.email,
        password: form.password,
        name: form.name,
        age: Number(form.age),
        institution: form.institution || undefined,
        country: form.country || undefined,
        research_area: form.research_area || undefined,
        purpose: form.purpose,
      });
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed");
    } finally {
      setSubmitting(false);
    }
  }

  if (submitted) {
    return (
      <main className="mx-auto max-w-md px-6 py-20">
        <h1 className="text-2xl font-semibold">Check your email</h1>
        <p className="mt-3 text-slate-600">
          We sent a verification link to <strong>{form.email}</strong>. Click
          it to activate your account and receive your first API key.
        </p>
        <p className="mt-6 text-sm text-slate-500">
          The link expires in 24 hours.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <h1 className="text-2xl font-semibold">Create an SCLib account</h1>
      <p className="mt-1 text-sm text-slate-600">
        All fields marked * are required. You must be 13 or older.
      </p>

      <form onSubmit={onSubmit} className="mt-8 space-y-4">
        <Field label="Email *" type="email" value={form.email}
               onChange={(v) => update("email", v)} required />
        <Field label="Password * (min 8 chars)" type="password"
               value={form.password} onChange={(v) => update("password", v)} required />
        <Field label="Full name *" value={form.name}
               onChange={(v) => update("name", v)} required />
        <Field label="Age *" type="number" value={form.age}
               onChange={(v) => update("age", v)} required />
        <Field label="Institution" value={form.institution}
               onChange={(v) => update("institution", v)} />
        <Field label="Country" value={form.country}
               onChange={(v) => update("country", v)} />
        <Field label="Research area" value={form.research_area}
               onChange={(v) => update("research_area", v)} />
        <label className="block">
          <span className="text-sm font-medium">Purpose of use *</span>
          <textarea
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            value={form.purpose}
            onChange={(e) => update("purpose", e.target.value)}
            required
            minLength={10}
            rows={3}
          />
        </label>

        {error && (
          <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {submitting ? "Creating…" : "Create account"}
        </button>

        <p className="text-center text-sm text-slate-600">
          Already have an account?{" "}
          <Link href="/login" className="text-slate-900 underline">
            Sign in
          </Link>
        </p>
      </form>
    </main>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  required = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium">{label}</span>
      <input
        className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
      />
    </label>
  );
}
