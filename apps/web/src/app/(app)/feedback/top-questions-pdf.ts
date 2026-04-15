import jsPDF from "jspdf";
import autoTable from "jspdf-autotable";
import type { TopQuestionsResponse } from "@/lib/api";

export function downloadTopQuestionsPdf(result: TopQuestionsResponse): void {
  const doc = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });

  // Title
  doc.setFontSize(18);
  doc.text("Top Questions Report", 14, 20);

  // Metadata
  doc.setFontSize(10);
  doc.setTextColor(100);
  const dateStr = result.completed_at
    ? new Date(result.completed_at).toLocaleString("de-DE", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "N/A";
  doc.text(
    `Generated: ${dateStr}  |  ${result.total_questions} questions analyzed`,
    14,
    28,
  );
  doc.setTextColor(0);

  let yPos = 36;

  for (const theme of result.themes) {
    // New page if running low on space
    if (yPos > 250) {
      doc.addPage();
      yPos = 20;
    }

    // Theme header
    doc.setFontSize(13);
    doc.setFont(undefined as unknown as string, "bold");
    doc.text(`#${theme.rank}  ${theme.theme}`, 14, yPos);
    yPos += 6;

    // Count + sentiment
    doc.setFontSize(9);
    doc.setFont(undefined as unknown as string, "normal");
    doc.setTextColor(80);
    const pos = theme.feedback_sentiment.positive;
    const neg = theme.feedback_sentiment.negative;
    doc.text(
      `${theme.count} questions  |  Answer Feedback: ${pos} positive, ${neg} negative`,
      14,
      yPos,
    );
    yPos += 5;

    // Summary question
    if (theme.summary_question) {
      doc.setFont(undefined as unknown as string, "italic");
      const lines = doc.splitTextToSize(
        `"${theme.summary_question}"`,
        180,
      ) as string[];
      doc.text(lines, 14, yPos);
      yPos += lines.length * 4 + 2;
    }

    doc.setTextColor(0);
    doc.setFont(undefined as unknown as string, "normal");

    // Questions table
    const tableData = theme.all_questions.map((q, i) => [
      String(i + 1),
      q.question,
      q.feedback_value === 1
        ? "Positive"
        : q.feedback_value === 0
          ? "Negative"
          : "\u2014",
    ]);

    autoTable(doc, {
      startY: yPos,
      head: [["#", "Question", "Answer Feedback"]],
      body: tableData,
      theme: "grid",
      headStyles: { fillColor: [79, 70, 229], fontSize: 8 },
      bodyStyles: { fontSize: 8 },
      columnStyles: {
        0: { cellWidth: 10, halign: "center" },
        1: { cellWidth: 145 },
        2: { cellWidth: 25, halign: "center" },
      },
      margin: { left: 14, right: 14 },
      didParseCell: (data) => {
        if (data.section === "body" && data.column.index === 2) {
          if (data.cell.raw === "Positive") {
            data.cell.styles.textColor = [34, 197, 94];
          } else if (data.cell.raw === "Negative") {
            data.cell.styles.textColor = [239, 68, 68];
          }
        }
      },
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    yPos = (doc as any).lastAutoTable.finalY + 10;
  }

  doc.save(`top-questions-report.pdf`);
}
