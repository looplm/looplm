import Link from "next/link";
import LoopLMIcon from "@/components/looplm-icon";

export default function Home() {
  const repositoryUrl = process.env.NEXT_PUBLIC_REPOSITORY_URL?.trim();

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-indigo-50 dark:from-slate-950 dark:via-slate-900 dark:to-indigo-950 text-gray-900 dark:text-white">
      <nav className="flex items-center justify-between px-8 py-6 max-w-7xl mx-auto">
        <div className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <LoopLMIcon className="w-7 h-7 text-indigo-600 dark:text-indigo-400" />
          <span><span className="text-indigo-600 dark:text-indigo-400">Loop</span>LM</span>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/login"
            className="px-4 py-2 text-sm font-medium text-gray-600 dark:text-slate-300 hover:text-gray-900 dark:hover:text-white transition-colors"
          >
            Sign in
          </Link>
          <Link
            href="/register"
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm font-medium text-white transition-colors"
          >
            Get Started
          </Link>
        </div>
      </nav>

      <main className="flex flex-col items-center justify-center px-8 pt-32 pb-20 max-w-4xl mx-auto text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 mb-8 text-xs font-medium bg-indigo-500/10 border border-indigo-500/20 rounded-full text-indigo-600 dark:text-indigo-300">
          🚀 Now in development
        </div>

        <h1 className="text-5xl sm:text-6xl font-bold tracking-tight leading-tight mb-6">
          From traces to{" "}
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-purple-400">
            fixes
          </span>
        </h1>

        <p className="text-lg text-gray-500 dark:text-slate-400 max-w-2xl mb-12 leading-relaxed">
          LoopLM connects to your existing LLM observability stack — LangSmith,
          Langfuse, and more — automatically detects failures, identifies root
          causes, and suggests concrete fixes.
        </p>

        <div className="flex gap-4">
          <Link
            href="/dashboard"
            className="px-6 py-3 bg-indigo-600 hover:bg-indigo-500 rounded-lg font-medium text-white transition-colors"
          >
            Get Started
          </Link>
          {repositoryUrl && (
            <a
              href={repositoryUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="px-6 py-3 border border-gray-200 dark:border-slate-700 hover:border-gray-400 dark:hover:border-slate-500 rounded-lg font-medium transition-colors"
            >
              GitHub
            </a>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-8 mt-24 w-full">
          {[
            {
              title: "Connect",
              desc: "Pull traces from LangSmith, Langfuse, or any supported platform.",
            },
            {
              title: "Analyze",
              desc: "Automatic failure detection, root cause analysis, and pattern clustering.",
            },
            {
              title: "Fix",
              desc: "Get concrete fix suggestions — prompt rewrites, tool configs, knowledge base gaps.",
            },
          ].map((item) => (
            <div
              key={item.title}
              className="p-6 rounded-xl bg-gray-100/50 dark:bg-slate-800/50 border border-gray-200/50 dark:border-slate-700/50"
            >
              <h3 className="text-lg font-semibold mb-2">{item.title}</h3>
              <p className="text-sm text-gray-500 dark:text-slate-400">{item.desc}</p>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
