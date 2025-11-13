{{/*
Expand the name of the chart.
*/}}
{{- define "ren3.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "ren3.fullname" -}}
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
{{- define "ren3.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "ren3.labels" -}}
helm.sh/chart: {{ include "ren3.chart" . }}
{{ include "ren3.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "ren3.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ren3.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "ren3.serviceAccountName" -}}
{{- default (include "ren3.fullname" .) .Values.serviceAccount.name }}
{{- end }}

{{/*
ConfigMaps data
*/}}
{{- define "ren3.configMapData" -}}
{{- range $envKey, $envVal := .Values.env.normal }}
  {{ $envKey | upper }}: {{ $envVal | quote }}
{{- end }}
{{- end }}

{{/*
Secrets data
*/}}
{{- define "ren3.secretData" -}}
{{- range $envKey, $envVal := .Values.env.secret }}
  {{ $envKey | upper }}: {{ $envVal | b64enc | quote }}
{{- end }}
{{- end }}

