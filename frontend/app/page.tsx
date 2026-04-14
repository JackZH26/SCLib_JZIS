import Link from "next/link";

export default function Landing() {
  return (
    <main className="mx-auto max-w-2xl px-6 py-20">
      <h1 className="text-4xl font-bold tracking-tight">SCLib</h1>
      <p className="mt-2 text-lg text-slate-600">
        JZIS Superconductivity Library — self-hosted search, RAG, and material
        data for superconductivity research.
      </p>
      <div className="mt-10 flex gap-4">
        <Link
          href="/register"
          className="rounded-md bg-slate-900 px-5 py-2 text-white hover:bg-slate-700"
        >
          Create account
        </Link>
        <Link
          href="/login"
          className="rounded-md border border-slate-300 px-5 py-2 hover:bg-slate-100"
        >
          Sign in
        </Link>
      </div>
      <p className="mt-8 text-sm text-slate-500">
        Phase 1 preview — search, RAG, and material pages come online after
        Phase 2 ingestion.
      </p>
    </main>
  );
}
