{{/*
Expand the name of the chart.
*/}}
{{- define "cloudflare-dyndns.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "cloudflare-dyndns.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "cloudflare-dyndns.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "cloudflare-dyndns.labels" -}}
helm.sh/chart: {{ include "cloudflare-dyndns.chart" . }}
{{ include "cloudflare-dyndns.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "cloudflare-dyndns.selectorLabels" -}}
app.kubernetes.io/name: {{ include "cloudflare-dyndns.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "cloudflare-dyndns.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "cloudflare-dyndns.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
CFDD_* environment variables rendered from .Values.config
*/}}
{{- define "cloudflare-dyndns.env" -}}
- name: CFDD_HOST
  value: "0.0.0.0"
- name: CFDD_PORT
  value: "8080"
- name: CFDD_LOG_LEVEL
  value: {{ .Values.config.logLevel | quote }}
- name: CFDD_LOG_FORMAT
  value: {{ .Values.config.logFormat | quote }}
- name: CFDD_ALLOWED_ZONES
  value: {{ .Values.config.allowedZones | quote }}
- name: CFDD_CREATE_MISSING_RECORDS
  value: {{ .Values.config.createMissingRecords | quote }}
- name: CFDD_DEFAULT_TTL
  value: {{ .Values.config.defaultTtl | quote }}
- name: CFDD_DEFAULT_PROXIED
  value: {{ .Values.config.defaultProxied | quote }}
- name: CFDD_ZONE_CACHE_TTL
  value: {{ .Values.config.zoneCacheTtl | quote }}
- name: CFDD_RECORD_CACHE_TTL
  value: {{ .Values.config.recordCacheTtl | quote }}
- name: CFDD_CACHE_MAX_ENTRIES
  value: {{ .Values.config.cacheMaxEntries | quote }}
- name: CFDD_CF_TIMEOUT
  value: {{ .Values.config.cfTimeout | quote }}
- name: CFDD_CF_MAX_RETRIES
  value: {{ .Values.config.cfMaxRetries | quote }}
- name: CFDD_RATE_LIMIT_ENABLED
  value: {{ .Values.config.rateLimitEnabled | quote }}
- name: CFDD_RATE_LIMIT_PER_MINUTE
  value: {{ .Values.config.rateLimitPerMinute | quote }}
- name: CFDD_RATE_LIMIT_BURST
  value: {{ .Values.config.rateLimitBurst | quote }}
- name: CFDD_TRUSTED_PROXIES
  value: {{ .Values.config.trustedProxies | quote }}
- name: CFDD_METRICS_ENABLED
  value: {{ .Values.config.metricsEnabled | quote }}
- name: CFDD_DOCS_ENABLED
  value: {{ .Values.config.docsEnabled | quote }}
{{- end }}
