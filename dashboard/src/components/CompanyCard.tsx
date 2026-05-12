import { Link } from '@tanstack/react-router'
import type { Company } from '~/lib/dri-api'

interface Props {
  company: Company
}

export function CompanyCard({ company }: Props) {
  const date = new Date(company.created_at).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })

  return (
    <Link
      to="/companies/$companyId"
      params={{ companyId: company.id }}
      className="block p-5 bg-zinc-900 border border-zinc-800 rounded-xl hover:border-zinc-600 transition-colors group"
    >
      <div className="flex items-start justify-between gap-2 mb-3">
        <h3 className="font-semibold text-zinc-50 group-hover:text-white leading-tight">
          {company.name}
        </h3>
        <span
          className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-mono ${
            company.status === 'active'
              ? 'bg-emerald-900 text-emerald-400'
              : 'bg-zinc-800 text-zinc-500'
          }`}
        >
          {company.status}
        </span>
      </div>
      <p className="text-zinc-400 text-sm leading-relaxed line-clamp-2 mb-4">
        {company.vision || company.pitch}
      </p>
      <p className="text-zinc-600 text-xs font-mono">Created {date}</p>
    </Link>
  )
}
