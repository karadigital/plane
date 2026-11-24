/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Document, Page, StyleSheet, Text, View } from "@react-pdf/renderer";
// plane imports
import { renderFormattedDate } from "@plane/utils";
// local imports
import { PDF_FONT_FAMILY } from "@/components/editor/pdf/fonts";
import type { TAutoReport, TAutoReportGroup } from "@/services/auto-report.service";
import { buildGanttLayout, collapseWhitespace, formatRowLabel } from "./gantt-layout";

type Props = {
  report: TAutoReport;
  generatedAt: Date;
  t: (key: string, params?: Record<string, unknown>) => string;
};

const KEY = "workspace_settings.settings.exports.auto_report";
const GROUPS: TAutoReportGroup[] = ["finished", "in_progress", "pipeline"];
const LABEL_WIDTH = 200;

const styles = StyleSheet.create({
  page: { fontFamily: PDF_FONT_FAMILY, fontSize: 9, padding: 32, color: "#1f2937", backgroundColor: "#ffffff" },
  title: { fontSize: 18, fontWeight: "bold", marginBottom: 4 },
  meta: { fontSize: 10, color: "#4b5563", marginBottom: 2 },
  sectionTitle: { fontSize: 12, fontWeight: "semibold", marginTop: 16, marginBottom: 6 },
  ganttRow: { flexDirection: "row", alignItems: "center", height: 14 },
  ganttLabel: { width: LABEL_WIDTH, paddingRight: 6, fontSize: 8 },
  ganttTrack: { flexGrow: 1, position: "relative", height: 14, borderBottom: "0.5px solid #f3f4f6" },
  ganttBar: { position: "absolute", top: 3, height: 8, backgroundColor: "#3f76ff", borderRadius: 2 },
  ganttMarker: { backgroundColor: "#f59e0b" },
  tickLabel: { position: "absolute", fontSize: 7, color: "#6b7280" },
  tickLine: { position: "absolute", top: 0, bottom: 0, borderLeft: "0.5px solid #e5e7eb" },
  note: { fontSize: 8, color: "#6b7280", marginTop: 4 },
  tableHeader: { flexDirection: "row", fontWeight: "semibold", borderBottom: "1px solid #d1d5db", paddingBottom: 3 },
  tableRow: { flexDirection: "row", borderBottom: "0.5px solid #e5e7eb", paddingVertical: 3 },
  colKey: { width: 70 },
  colName: { flex: 1, paddingRight: 8 },
  colState: { width: 100 },
  colDate: { width: 80 },
  empty: { color: "#6b7280", paddingVertical: 3 },
});

const formatDate = (value: string | null) => (value ? (renderFormattedDate(value) ?? "") : "");

export function AutoReportDocument(props: Props) {
  const { report, generatedAt, t } = props;
  const { period, projects, items } = report;
  const layout = buildGanttLayout(items, period.start, period.pipeline_end);
  const itemById = new Map(items.map((item) => [item.id, item]));

  return (
    <Document>
      <Page size="A4" orientation="landscape" style={styles.page}>
        <Text style={styles.title}>{t(`${KEY}.title`)}</Text>
        <Text style={styles.meta}>
          {t(`${KEY}.period`)}: {formatDate(period.start)} – {formatDate(period.end)}
        </Text>
        <Text style={styles.meta}>
          {t(`${KEY}.projects`)}: {projects.map((project) => `${project.name} (${project.identifier})`).join(", ")}
        </Text>
        <Text style={styles.meta}>{t(`${KEY}.generated`, { date: renderFormattedDate(generatedAt) })}</Text>

        <View style={{ marginTop: 16 }}>
          <View style={styles.ganttRow}>
            <View style={styles.ganttLabel} />
            <View style={styles.ganttTrack}>
              {layout.ticks.map((tick) => (
                <Text key={tick.date} style={[styles.tickLabel, { left: `${tick.leftPct}%` }]}>
                  {renderFormattedDate(tick.date, "MMM dd")}
                </Text>
              ))}
            </View>
          </View>
          {layout.rows.map((row) => {
            const item = itemById.get(row.id);
            return (
              <View key={row.id} style={styles.ganttRow} wrap={false}>
                <Text style={styles.ganttLabel}>{item ? formatRowLabel(item.key, item.name) : ""}</Text>
                <View style={styles.ganttTrack}>
                  {layout.ticks.map((tick) => (
                    <View key={tick.date} style={[styles.tickLine, { left: `${tick.leftPct}%` }]} />
                  ))}
                  <View
                    style={[
                      styles.ganttBar,
                      ...(row.isMarker ? [styles.ganttMarker] : []),
                      { left: `${row.leftPct}%`, width: `${row.widthPct}%` },
                    ]}
                  />
                </View>
              </View>
            );
          })}
          {layout.noDateCount > 0 && (
            <Text style={styles.note}>{t(`${KEY}.no_dates_note`, { count: layout.noDateCount })}</Text>
          )}
          {layout.outOfRangeCount > 0 && (
            <Text style={styles.note}>{t(`${KEY}.out_of_range_note`, { count: layout.outOfRangeCount })}</Text>
          )}
        </View>

        {GROUPS.map((group) => {
          const groupItems = items.filter((item) => item.groups.includes(group));
          return (
            <View key={group}>
              <Text style={styles.sectionTitle}>{t(`${KEY}.${group}`)}</Text>
              <View style={styles.tableHeader}>
                <Text style={styles.colKey}>{t(`${KEY}.key`)}</Text>
                <Text style={styles.colName}>{t(`${KEY}.name`)}</Text>
                <Text style={styles.colState}>{t(`${KEY}.state`)}</Text>
                <Text style={styles.colDate}>{t(`${KEY}.start_date`)}</Text>
                <Text style={styles.colDate}>{t(`${KEY}.due_date`)}</Text>
              </View>
              {groupItems.length === 0 ? (
                <Text style={styles.empty}>{t(`${KEY}.no_items`)}</Text>
              ) : (
                groupItems.map((item) => (
                  <View key={item.id} style={styles.tableRow} wrap={false}>
                    <Text style={styles.colKey}>{item.key}</Text>
                    <Text style={styles.colName}>{collapseWhitespace(item.name)}</Text>
                    <Text style={styles.colState}>{item.state_name}</Text>
                    <Text style={styles.colDate}>{formatDate(item.start_date)}</Text>
                    <Text style={styles.colDate}>{formatDate(item.target_date)}</Text>
                  </View>
                ))
              )}
            </View>
          );
        })}
      </Page>
    </Document>
  );
}
