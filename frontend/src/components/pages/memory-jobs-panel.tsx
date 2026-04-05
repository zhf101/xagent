"use client"

import React, { useCallback, useEffect, useMemo, useState } from "react"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select-radix"
import { Switch } from "@/components/ui/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useI18n } from "@/contexts/i18n-context"
import { apiRequest } from "@/lib/api-wrapper"
import { getApiUrl } from "@/lib/utils"
import { cn } from "@/lib/utils"
import { Clock3, RefreshCw, RotateCcw, Workflow } from "lucide-react"

interface MemoryJobItem {
  id: number
  job_type: string
  status: string
  priority: number
  payload_json: Record<string, any>
  dedupe_key?: string | null
  source_task_id?: string | null
  source_session_id?: string | null
  source_user_id?: number | null
  source_project_id?: string | null
  attempt_count: number
  max_attempts: number
  available_at: string
  lease_until?: string | null
  locked_by?: string | null
  last_error?: string | null
  created_at: string
  updated_at?: string | null
  started_at?: string | null
  finished_at?: string | null
}

interface MemoryJobListResponse {
  jobs: MemoryJobItem[]
  total_count: number
  filters_used: Record<string, any>
}

const RETRIABLE_STATUSES = new Set(["failed", "dead", "cancelled"])
const KNOWN_JOB_STATUSES = ["pending", "running", "succeeded", "failed", "dead", "cancelled"] as const
const KNOWN_JOB_TYPES = ["extract_memories", "consolidate_memories", "expire_memories"] as const
const ALL_FILTER_VALUE = "all"
const AUTO_REFRESH_INTERVAL_MS = 10_000
const JOBS_PAGE_SIZE = 20

function truncate(value?: string | null, maxLength: number = 48): string {
  if (!value) return "-"
  if (value.length <= maxLength) return value
  return `${value.slice(0, maxLength - 1)}...`
}

function getStatusBadgeClass(status: string): string {
  switch (status) {
    case "pending":
      return "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200"
    case "running":
      return "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
    case "succeeded":
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300"
    case "failed":
      return "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
    case "dead":
      return "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300"
    case "cancelled":
      return "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
    default:
      return "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200"
  }
}

export function MemoryJobsPanel() {
  const { t, locale } = useI18n()
  const [jobs, setJobs] = useState<MemoryJobItem[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState(ALL_FILTER_VALUE)
  const [jobTypeFilter, setJobTypeFilter] = useState(ALL_FILTER_VALUE)
  const [selectedJob, setSelectedJob] = useState<MemoryJobItem | null>(null)
  const [retryingJobId, setRetryingJobId] = useState<number | null>(null)
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true)
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null)
  const [currentPage, setCurrentPage] = useState(1)

  const formatDate = useCallback((value?: string | null) => {
    if (!value) return "-"
    const lang = locale === "zh" ? "zh-CN" : "en-US"
    return new Date(value).toLocaleString(lang)
  }, [locale])

  const statusOptions = useMemo(
    () => [ALL_FILTER_VALUE, ...KNOWN_JOB_STATUSES],
    []
  )

  const jobTypeOptions = useMemo(() => {
    const merged = new Set<string>(KNOWN_JOB_TYPES)
    jobs.forEach(job => merged.add(job.job_type))
    return [ALL_FILTER_VALUE, ...Array.from(merged)]
  }, [jobs])

  const totalPages = Math.max(1, Math.ceil(totalCount / JOBS_PAGE_SIZE))
  const pageStart = totalCount === 0 ? 0 : (currentPage - 1) * JOBS_PAGE_SIZE + 1
  const pageEnd = totalCount === 0 ? 0 : Math.min(currentPage * JOBS_PAGE_SIZE, totalCount)

  const fetchJobs = useCallback(async (options?: { silent?: boolean }) => {
    try {
      if (!options?.silent) {
        setLoading(true)
      }
      setError(null)
      const params = new URLSearchParams()
      if (statusFilter !== ALL_FILTER_VALUE) params.append("status", statusFilter)
      if (jobTypeFilter !== ALL_FILTER_VALUE) params.append("job_type", jobTypeFilter)
      params.append("limit", String(JOBS_PAGE_SIZE))
      params.append("offset", String((currentPage - 1) * JOBS_PAGE_SIZE))

      const response = await apiRequest(`${getApiUrl()}/api/memory/jobs?${params.toString()}`, {
        headers: {},
      })
      if (!response.ok) throw new Error(t("memory.jobs.errors.loadFailed"))
      const data: MemoryJobListResponse = await response.json()
      setJobs(data.jobs)
      setTotalCount(data.total_count)
      setSelectedJob(currentSelected =>
        currentSelected
          ? data.jobs.find(job => job.id === currentSelected.id) ?? data.jobs[0] ?? null
          : data.jobs[0] ?? null
      )
      setLastRefreshedAt(new Date().toISOString())
    } catch (err) {
      setError(err instanceof Error ? err.message : t("memory.jobs.errors.loadFailed"))
    } finally {
      if (!options?.silent) {
        setLoading(false)
      }
    }
  }, [currentPage, jobTypeFilter, statusFilter, t])

  const handleStatusFilterChange = (value: string) => {
    setStatusFilter(value)
    setCurrentPage(1)
  }

  const handleJobTypeFilterChange = (value: string) => {
    setJobTypeFilter(value)
    setCurrentPage(1)
  }

  useEffect(() => {
    fetchJobs()
  }, [fetchJobs])

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages)
    }
  }, [currentPage, totalPages])

  useEffect(() => {
    if (!autoRefreshEnabled) return
    const timer = window.setInterval(() => {
      fetchJobs({ silent: true })
    }, AUTO_REFRESH_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [autoRefreshEnabled, fetchJobs])

  const handleRetry = async (jobId: number) => {
    try {
      setRetryingJobId(jobId)
      setError(null)
      const response = await apiRequest(`${getApiUrl()}/api/memory/jobs/${jobId}/retry`, {
        method: "POST",
        headers: {},
      })
      if (!response.ok) throw new Error(t("memory.jobs.errors.retryFailed"))
      await fetchJobs()
    } catch (err) {
      setError(err instanceof Error ? err.message : t("memory.jobs.errors.retryFailed"))
    } finally {
      setRetryingJobId(null)
    }
  }

  return (
    <div className="space-y-6 px-8 py-6">
      <div className="flex flex-col gap-4 rounded-2xl border bg-card p-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 className="text-lg font-semibold">{t("memory.jobs.title")}</h3>
          <p className="text-sm text-muted-foreground">{t("memory.jobs.description")}</p>
        </div>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-3 sm:flex-row">
            <Select value={statusFilter} onValueChange={handleStatusFilterChange}>
              <SelectTrigger className="sm:w-44" aria-label={t("memory.jobs.filters.statusLabel")}>
                <SelectValue placeholder={t("memory.jobs.filters.statusPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {statusOptions.map(status => (
                  <SelectItem key={status} value={status}>
                    {status === ALL_FILTER_VALUE
                      ? t("memory.jobs.filters.allStatuses")
                      : t(`memory.jobs.statusOptions.${status}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={jobTypeFilter} onValueChange={handleJobTypeFilterChange}>
              <SelectTrigger className="sm:w-52" aria-label={t("memory.jobs.filters.jobTypeLabel")}>
                <SelectValue placeholder={t("memory.jobs.filters.jobTypePlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {jobTypeOptions.map(jobType => (
                  <SelectItem key={jobType} value={jobType}>
                    {jobType === ALL_FILTER_VALUE
                      ? t("memory.jobs.filters.allJobTypes")
                      : t(`memory.jobs.jobTypeOptions.${jobType}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" onClick={() => fetchJobs()} disabled={loading}>
              <RefreshCw className={cn("mr-2 h-4 w-4", loading && "animate-spin")} />
              {t("memory.jobs.actions.refresh")}
            </Button>
          </div>
          <div className="flex flex-col gap-2 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <Switch
                checked={autoRefreshEnabled}
                onCheckedChange={setAutoRefreshEnabled}
                aria-label={t("memory.jobs.autoRefresh.label")}
              />
              <Label className="text-xs font-medium text-foreground">
                {t("memory.jobs.autoRefresh.label")}
              </Label>
              <span>{t("memory.jobs.autoRefresh.hint", { seconds: AUTO_REFRESH_INTERVAL_MS / 1000 })}</span>
            </div>
            <div className="flex items-center gap-1">
              <Clock3 className="h-3.5 w-3.5" />
              <span>
                {t("memory.jobs.autoRefresh.lastRefreshed", {
                  time: lastRefreshedAt ? formatDate(lastRefreshedAt) : "-",
                })}
              </span>
            </div>
          </div>
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(320px,0.9fr)]">
        <Card className="overflow-hidden">
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("memory.jobs.columns.job")}</TableHead>
                  <TableHead>{t("memory.jobs.columns.status")}</TableHead>
                  <TableHead>{t("memory.jobs.columns.source")}</TableHead>
                  <TableHead>{t("memory.jobs.columns.attempts")}</TableHead>
                  <TableHead>{t("memory.jobs.columns.updatedAt")}</TableHead>
                  <TableHead className="w-[120px]">{t("memory.jobs.columns.actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  <TableRow>
                    <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                      {t("memory.loading")}
                    </TableCell>
                  </TableRow>
                ) : jobs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                      {t("memory.jobs.empty")}
                    </TableCell>
                  </TableRow>
                ) : (
                  jobs.map(job => (
                    <TableRow
                      key={job.id}
                      data-state={selectedJob?.id === job.id ? "selected" : undefined}
                      className="cursor-pointer"
                      onClick={() => setSelectedJob(job)}
                    >
                      <TableCell>
                        <div className="space-y-1">
                          <div className="font-medium">{t(`memory.jobs.jobTypeOptions.${job.job_type}`)}</div>
                          <div className="text-xs text-muted-foreground">#{job.id}</div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge className={cn("border-0", getStatusBadgeClass(job.status))}>
                          {t(`memory.jobs.statusOptions.${job.status}`)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        <div>{truncate(job.source_task_id)}</div>
                        <div>{truncate(job.source_project_id)}</div>
                      </TableCell>
                      <TableCell>{job.attempt_count}/{job.max_attempts}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDate(job.updated_at ?? job.created_at)}
                      </TableCell>
                      <TableCell>
                        {RETRIABLE_STATUSES.has(job.status) ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={event => {
                              event.stopPropagation()
                              handleRetry(job.id)
                            }}
                            disabled={retryingJobId === job.id}
                          >
                            <RotateCcw className="mr-2 h-3.5 w-3.5" />
                            {retryingJobId === job.id
                              ? t("memory.jobs.actions.retrying")
                              : t("memory.jobs.actions.retry")}
                          </Button>
                        ) : (
                          <span className="text-xs text-muted-foreground">-</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
            <div className="flex items-center justify-between border-t bg-card px-4 py-3 text-sm">
              <span className="text-muted-foreground">
                {t("memory.jobs.pagination.summary", {
                  from: pageStart,
                  to: pageEnd,
                  total: totalCount,
                })}
              </span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  {t("memory.jobs.pagination.page", { current: currentPage, total: totalPages })}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setCurrentPage(page => Math.max(1, page - 1))}
                  disabled={currentPage <= 1 || loading}
                >
                  {t("memory.jobs.pagination.prev")}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setCurrentPage(page => Math.min(totalPages, page + 1))}
                  disabled={currentPage >= totalPages || loading}
                >
                  {t("memory.jobs.pagination.next")}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-4 p-5">
            <div className="flex items-center gap-2">
              <Workflow className="h-4 w-4 text-muted-foreground" />
              <h4 className="font-semibold">{t("memory.jobs.detail.title")}</h4>
            </div>

            {!selectedJob ? (
              <p className="text-sm text-muted-foreground">{t("memory.jobs.detail.empty")}</p>
            ) : (
              <>
                <div className="grid gap-3 text-sm">
                  <div>
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">
                      {t("memory.jobs.detail.jobType")}
                    </div>
                    <div className="mt-1 font-medium">{t(`memory.jobs.jobTypeOptions.${selectedJob.job_type}`)}</div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">
                      {t("memory.jobs.detail.status")}
                    </div>
                    <div className="mt-1">
                      <Badge className={cn("border-0", getStatusBadgeClass(selectedJob.status))}>
                        {t(`memory.jobs.statusOptions.${selectedJob.status}`)}
                      </Badge>
                    </div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">
                      {t("memory.jobs.detail.source")}
                    </div>
                    <div className="mt-1 space-y-1 text-muted-foreground">
                      <div>task: {selectedJob.source_task_id || "-"}</div>
                      <div>session: {selectedJob.source_session_id || "-"}</div>
                      <div>project: {selectedJob.source_project_id || "-"}</div>
                    </div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">
                      {t("memory.jobs.detail.lastError")}
                    </div>
                    <div className="mt-1 whitespace-pre-wrap rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">
                      {selectedJob.last_error || "-"}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">
                      {t("memory.jobs.detail.payload")}
                    </div>
                    <pre className="mt-1 overflow-auto rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">
                      {JSON.stringify(selectedJob.payload_json, null, 2)}
                    </pre>
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
