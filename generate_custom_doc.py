"""
VidyutDrishti Custom Technical Document Generator
Generates a comprehensive technical document complementing the pitch deck
"""

from fpdf import FPDF
import os

class VidyutDrishtiDoc(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(left=20, top=20, right=20)
        
        # Color palette — clean professional print scheme
        self.color_primary = (15, 23, 42)       # Near-black (slate-900)
        self.color_secondary = (30, 64, 175)    # Deep blue (blue-800)
        self.color_accent = (220, 38, 38)       # Deep red
        self.color_success = (21, 128, 61)      # Deep green
        self.color_warning = (161, 98, 7)       # Amber-700
        self.color_light = (248, 250, 252)      # Off-white
        self.color_dark = (15, 23, 42)          # Near-black
        self.color_body = (30, 41, 59)          # Slate-800
        
    def header(self):
        self.set_font('helvetica', 'B', 12)
        self.set_text_color(*self.color_primary)
        self.cell(0, 10, 'VidyutDrishti Technical Documentation', new_x='LMARGIN', new_y='NEXT', align='C')
        self.set_font('helvetica', '', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 5, 'VidyutDrishti: AT&C Loss Recovery Intelligence System for BESCOM', new_x='LMARGIN', new_y='NEXT', align='C')
        self.ln(5)
        
    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')
        
    def chapter_title(self, title, number):
        self.set_fill_color(*self.color_primary)
        self.set_text_color(255, 255, 255)
        self.set_font('helvetica', 'B', 14)
        self.cell(0, 10, f'{number}. {title}', new_x='LMARGIN', new_y='NEXT', align='L', fill=True)
        self.ln(4)
        
    def section_title(self, title):
        self.set_text_color(*self.color_secondary)
        self.set_font('helvetica', 'B', 12)
        self.cell(0, 8, title, new_x='LMARGIN', new_y='NEXT', align='L')
        self.ln(2)
        
    def body_text(self, text):
        self.set_text_color(*self.color_body)
        self.set_font('helvetica', '', 10)
        self.multi_cell(0, 5, text)
        self.ln(3)
        
    def bullet_list(self, items):
        self.set_text_color(*self.color_body)
        self.set_font('helvetica', '', 10)
        for item in items:
            self.set_x(25)
            self.multi_cell(170, 5, f'- {item}')
        self.ln(3)
        
    def table(self, headers, rows, col_widths=None):
        total_w = self.w - 30
        n = len(headers)
        if col_widths is None:
            col_widths = [total_w / n] * n
        else:
            # scale provided ratios to fill total_w
            s = sum(col_widths)
            col_widths = [total_w * c / s for c in col_widths]

        # header row
        self.set_font('helvetica', 'B', 9)
        self.set_fill_color(*self.color_secondary)
        self.set_text_color(255, 255, 255)
        for w, header in zip(col_widths, headers):
            self.cell(w, 7, header, 1, new_x='RIGHT', new_y='TOP', align='C', fill=True)
        self.ln()

        # data rows — compute row height from tallest cell, then render
        self.set_font('helvetica', '', 8)
        self.set_text_color(*self.color_dark)
        LINE_H = 4.5

        for i, row in enumerate(rows):
            bg = (255, 255, 255) if i % 2 == 0 else self.color_light
            self.set_fill_color(*bg)

            # measure max lines needed in this row
            max_lines = 1
            for cell, cw in zip(row, col_widths):
                txt = str(cell)
                # rough char-per-line estimate at font size 8, ~1.8 pts/char
                chars_per_line = max(1, int(cw / 1.95))
                lines = 1
                words = txt.split()
                line_len = 0
                for word in words:
                    if line_len + len(word) + 1 > chars_per_line:
                        lines += 1
                        line_len = len(word)
                    else:
                        line_len += len(word) + 1
                max_lines = max(max_lines, lines)

            row_h = max_lines * LINE_H + 2

            # check page break
            if self.get_y() + row_h > self.h - self.b_margin:
                self.add_page()
                # re-draw header on new page
                self.set_font('helvetica', 'B', 9)
                self.set_fill_color(*self.color_secondary)
                self.set_text_color(255, 255, 255)
                for w, header in zip(col_widths, headers):
                    self.cell(w, 7, header, 1, new_x='RIGHT', new_y='TOP', align='C', fill=True)
                self.ln()
                self.set_font('helvetica', '', 8)
                self.set_text_color(*self.color_dark)
                self.set_fill_color(*bg)

            x0 = self.get_x()
            y0 = self.get_y()

            for cell, cw in zip(row, col_widths):
                x = self.get_x()
                # fill background rect
                self.set_fill_color(*bg)
                self.rect(x, y0, cw, row_h, 'F')
                # border
                self.set_draw_color(180, 180, 180)
                self.rect(x, y0, cw, row_h)
                # text via multi_cell
                self.set_xy(x + 1, y0 + 1)
                self.multi_cell(cw - 2, LINE_H, str(cell), border=0, align='L', fill=False, max_line_height=LINE_H)
                self.set_xy(x + cw, y0)

            self.set_xy(x0, y0 + row_h)
        self.ln(4)
        
    def note_box(self, text):
        self.set_fill_color(*self.color_light)
        self.set_draw_color(*self.color_secondary)
        y_pos = self.get_y()
        self.rect(10, y_pos, 190, 20, 'DF')
        self.set_text_color(*self.color_primary)
        self.set_font('helvetica', 'B', 9)
        self.cell(0, 5, 'NOTE', new_x='LMARGIN', new_y='NEXT', align='L')
        self.set_text_color(*self.color_body)
        self.set_font('helvetica', '', 9)
        self.multi_cell(0, 5, text)
        self.ln(5)


def generate_document():
    pdf = VidyutDrishtiDoc()
    pdf.add_page()
    
    # Cover
    pdf.ln(10)
    pdf.set_font('helvetica', 'B', 28)
    pdf.set_text_color(*pdf.color_primary)
    pdf.cell(0, 22, 'VidyutDrishti', new_x='LMARGIN', new_y='NEXT', align='C')
    pdf.set_font('helvetica', '', 15)
    pdf.set_text_color(*pdf.color_secondary)
    pdf.cell(0, 10, 'AT&C Loss Recovery Intelligence System for BESCOM', new_x='LMARGIN', new_y='NEXT', align='C')
    pdf.ln(6)
    pdf.set_draw_color(*pdf.color_secondary)
    pdf.set_line_width(0.8)
    pdf.line(30, pdf.get_y(), pdf.w - 30, pdf.get_y())
    pdf.ln(8)
    pdf.set_font('helvetica', '', 11)
    pdf.set_text_color(*pdf.color_body)
    pdf.cell(0, 8, 'Technical Documentation', new_x='LMARGIN', new_y='NEXT', align='C')
    pdf.ln(4)
    pdf.set_font('helvetica', '', 10)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 8, 'Hackathon Submission  ·  AI for Bharat  ·  Theme 8: Smart Meter Intelligence & Loss Detection', new_x='LMARGIN', new_y='NEXT', align='C')
    pdf.ln(14)
    
    # Table of Contents
    pdf.add_page()
    pdf.chapter_title('Table of Contents', '')
    toc = [
        ('1.', 'System Overview'),
        ('2.', 'Architecture'),
        ('3.', 'Data Ingestion Pipeline'),
        ('4.', 'Synthetic Data Simulator'),
        ('5.', 'User Workflow'),
        ('6.', 'Detection Algorithms'),
        ('7.', 'Evaluation Metrics'),
        ('8.', 'Deployment'),
        ('9.', 'Resource Requirements'),
        ('A.', 'Appendix: API Endpoints'),
        ('B.', 'Appendix: Development Practices & Code Quality'),
    ]
    pdf.set_font('helvetica', '', 11)
    pdf.set_text_color(*pdf.color_body)
    for num, title in toc:
        pdf.set_font('helvetica', 'B', 11)
        pdf.set_text_color(*pdf.color_secondary)
        pdf.cell(10, 9, num, new_x='RIGHT', new_y='TOP')
        pdf.set_font('helvetica', '', 11)
        pdf.set_text_color(*pdf.color_body)
        pdf.cell(0, 9, f'  {title}', new_x='LMARGIN', new_y='NEXT')
        pdf.set_draw_color(203, 213, 225)
        pdf.set_line_width(0.2)
        pdf.line(20, pdf.get_y(), pdf.w - 20, pdf.get_y())
        pdf.ln(1)
    
    # Section 1: System Overview
    pdf.add_page()
    pdf.chapter_title('System Overview', '1')
    pdf.section_title('Problem Statement')
    pdf.body_text(
        'BESCOM faces an estimated Rs. 1,800 crore annual revenue loss due to electricity theft. '
        'Current detection methods rely on annual audits with 6-12 month detection latency, '
        '40-50% false positive rates, and random sampling for inspections.'
    )
    
    pdf.section_title('Solution Overview')
    pdf.body_text(
        'VidyutDrishti is a real-time electricity theft detection system that processes '
        '15-minute meter readings from AMI infrastructure. It uses a 4-layer detection '
        'framework with weighted confidence scoring to generate prioritized inspection queues '
        'for BESCOM officers.'
    )

    pdf.section_title('Demo & Repository')
    pdf.bullet_list([
        'Demo video: https://drive.google.com/file/d/1LOgpMxeu2LzAK52B-go-8gtAn6rHe1Eu/view?usp=sharing',
        'Source code: https://github.com/srinidhirepala/VidyutDrishti',
        'Run locally: docker compose up  ->  localhost:5173 (UI)  |  localhost:8000/docs (API)',
    ])

    pdf.section_title('7 Working Modules (all live in submitted Docker stack)')
    headers = ['Module', 'What it shows']
    rows = [
        ['Dashboard', 'KPIs + 6 live charts + feeder forecast + loss by zone'],
        ['Inspection Queue', 'Ranked by Rs. x confidence | 14 active leads | status updates'],
        ['Meter Lookup', '4-layer drill-down | rule trace | confidence score per meter'],
        ['Zone Risk Map', 'Bengaluru Leaflet heatmap | 8 DT localities | HIGH/MEDIUM/LOW'],
        ['Feedback', 'Inspector outcome capture | triggers live queue + dashboard refresh'],
        ['Evaluation Metrics', 'Live P=78% | R=85% | F1=0.81 | detection lag=6.2d'],
        ['ROI Calculator', 'Interactive sliders | BESCOM-scale projection | 5-yr NPV'],
    ]
    pdf.table(headers, rows)
    
    # Section 2: Architecture
    pdf.add_page()
    pdf.chapter_title('Architecture', '2')
    pdf.section_title('System Components')
    components = [
        'AMI/MDM Integration: 15-minute meter readings ingestion',
        'TimescaleDB: Hypertable storage for time-series data',
        'Detection Engine: 4-layer anomaly detection with confidence scoring',
        'Queue Manager: Prioritised inspection list generation',
        'Feedback Loop: Inspector outcome integration for model improvement',
        'Dashboard: Real-time KPIs and zone risk visualization',
    ]
    pdf.bullet_list(components)
    
    pdf.section_title('Data Flow')
    pdf.body_text(
        'Data flows from AMI/MDM through ingestion pipelines into TimescaleDB. '
        'The detection engine processes new readings every 15 minutes, applying '
        '4-layer detection rules and computing confidence scores. Results are '
        'ranked by rupee value and presented in the dashboard for officer review.'
    )
    
    # Section 3: Data Ingestion Pipeline
    pdf.add_page()
    pdf.chapter_title('Data Ingestion Pipeline', '3')
    pdf.section_title('BESCOM AMI/MDM Integration')
    pdf.body_text(
        'The system integrates with BESCOMs existing AMI infrastructure through '
        'read-only API connections. No writes are performed to AMI, SCADA, MDM, '
        'or billing systems, ensuring zero operational risk.'
    )
    
    pdf.section_title('Data Sources')
    headers = ['Source', 'Frequency', 'Fields', 'Volume']
    rows = [
        ['Meter Readings', '15-min', 'meter_id, kWh, voltage, PF', '10M+ records/day'],
        ['DT Readings', '15-min', 'dt_id, kWh_in, kWh_out', '50K+ records/day'],
        ['Consumer Master', 'Daily', 'meter_id, tariff, category', '9M+ consumers'],
        ['DT Topology', 'Static', 'dt_id, connected_meters', '50K+ DTs'],
    ]
    pdf.table(headers, rows, col_widths=[2.5, 1.5, 3.5, 2.5])
    
    pdf.section_title('Ingestion Process')
    steps = [
        '1. Poll AMI/MDM APIs for new readings every 15 minutes',
        '2. Validate data quality (missing values, outliers, consistency checks)',
        '3. Apply missing-reading policies (forward-fill, interpolation, suspension)',
        '4. Insert into TimescaleDB hypertables with automatic partitioning',
        '5. Trigger detection pipeline for affected meters and DTs',
    ]
    pdf.bullet_list(steps)
    
    # Section 4: Synthetic Data Simulator
    pdf.add_page()
    pdf.chapter_title('Synthetic Data Simulator', '4')
    pdf.section_title('Purpose')
    pdf.body_text(
        'The simulator generates synthetic meter data with realistic consumption patterns '
        'and injected theft scenarios for testing and evaluation. This enables validation '
        'of detection algorithms without requiring access to real BESCOM data.'
    )
    
    pdf.section_title('Generation Workflow')
    workflow = [
        '1. Base load generation with diurnal patterns and seasonal variations',
        '2. Consumer categorization (domestic, commercial, industrial tariffs)',
        '3. DT topology assignment: 8 DTs, 60+ meters, realistic consumer-to-DT ratios',
        '4. Holiday effects and weekend patterns',
        '5. Theft scenario injection (hook bypass, meter tamper, meter stop)',
        '6. Ground truth labeling for evaluation metrics',
    ]
    pdf.bullet_list(workflow)
    
    pdf.section_title('Theft Scenarios')
    headers = ['Scenario', 'Description', 'Prevalence', 'Detection Layer']
    rows = [
        ['Hook Bypass', 'Direct wire connection bypassing meter', '40%', 'L0: DT Balance'],
        ['Meter Tamper', 'Physical meter modification or magnet', '30%', 'L1: Baseline'],
        ['Meter Stop', 'Meter completely disabled', '20%', 'L2: Peer Group'],
        ['Phase Imbalance', 'Illegal phase connection changes', '10%', 'L3: Voltage/PF'],
    ]
    pdf.table(headers, rows, col_widths=[2, 4, 1.5, 2.5])
    
    pdf.note_box(
        'CLI command: python -m simulator.generate --config simulator/config.yaml --out data/'
    )
    
    # Section 5: User Workflow
    pdf.add_page()
    pdf.chapter_title('User Workflow', '5')
    pdf.section_title('Officer Daily Operations')
    pdf.body_text(
        'BESCOM officers use VidyutDrishti through a web dashboard that presents '
        'prioritized inspection queues, detailed meter analysis, and feedback '
        'capture capabilities.'
    )
    
    pdf.section_title('Step 1: Dashboard Review')
    pdf.body_text(
        'Officers start their shift by reviewing the dashboard which shows '
        'high-level KPIs, zone risk heatmap, and top-priority inspection items. '
        'The queue is ranked by rupee value (confidence x estimated loss).'
    )
    
    pdf.section_title('Step 2: Inspection Queue')
    pdf.body_text(
        'Officers select items from the prioritized queue. Each item shows '
        '4-layer detection signals, confidence score, behavioral classification, '
        'and historical consumption patterns for context.'
    )
    
    pdf.section_title('Step 3: Field Inspection & Feedback')
    pdf.body_text(
        'After field inspection, officers log feedback (theft confirmed, '
        'false positive, or other outcome). This feedback is used to '
        'recalibrate detection thresholds and improve model accuracy over time.'
    )
    
    pdf.section_title('Role-Based Access')
    headers = ['Role', 'Permissions', 'Actions']
    rows = [
        ['Section Engineer', 'View queue, assign inspections', 'Prioritise and assign'],
        ['Field Inspector', 'View assigned items, log feedback', 'Execute inspections'],
        ['Ops Manager', 'View metrics, adjust thresholds', 'Monitor performance'],
    ]
    pdf.table(headers, rows)
    
    # Section 6: Detection Algorithms
    pdf.add_page()
    pdf.chapter_title('Detection Algorithms', '6')
    pdf.section_title('4-Layer Detection Framework')
    pdf.body_text(
        'Each layer catches a different theft pattern. Requiring multi-layer '
        'agreement reduces false positives while maintaining high recall.'
    )
    
    headers = ['Layer', 'Method', 'Threshold', 'Catches']
    rows = [
        ['L0: DT Balance', 'DT input - Sum consumer reads', '>8% imbalance, 3+ days', 'Hook bypass, large-scale tampering'],
        ['L1: Statistical Baseline', '90-day rolling z-score by hour/day/month', '|Z|>3.0, 4+ slots', 'Sudden drop/spike'],
        ['L2: Peer Comparison', 'Same DT + same category median', '-2.5 SD, 5+ days', 'Gradual theft, under-reporting'],
        ['L3: Isolation Forest', 'Multivariate features (kWh, PF, trend, zero-rate)', 'contamination=0.03, monthly retrain', 'Subtle pattern shifts, PF drops'],
    ]
    pdf.table(headers, rows, col_widths=[2, 3, 2.5, 2.5])
    
    pdf.section_title('Confidence Engine')
    pdf.body_text(
        'The confidence engine aggregates 4-layer signals using weighted '
        'contributions: L0 (10%), L1 (30%), L2 (30%), L3 (30%). '
        'Sigmoid normalization produces scores 0-1, classified as HIGH (>=0.85), '
        'MEDIUM (0.65-0.85), or REVIEW (0.50-0.65).'
    )
    
    pdf.section_title('Behavioural Classifier')
    classifications = [
        'sudden_drop: Abrupt consumption decrease',
        'gradual_decline: Slow consumption reduction over 5+ days',
        'spike: Unusual consumption increase',
        'flatline: Near-zero consumption',
        'erratic: Highly variable patterns',
        'normal_pattern: No anomaly detected',
    ]
    pdf.bullet_list(classifications)
    
    # Section 7: Evaluation Metrics
    pdf.add_page()
    pdf.chapter_title('Evaluation Metrics', '7')
    pdf.section_title('Live Performance')
    pdf.body_text(
        'All metrics are computed live by the evaluation harness against '
        'synthetic ground truth with injected theft scenarios.'
    )
    
    headers = ['Metric', 'Value', 'Target', 'Status']
    rows = [
        ['Precision @ HIGH', '78%', '>=70%', 'PASS'],
        ['Recall (hook bypass)', '85%', '>=85%', 'PASS'],
        ['F1 Score', '0.81', '>=0.75', 'PASS'],
        ['Mean Detection Lag', '6.2 days', '<10 days', 'PASS'],
    ]
    pdf.table(headers, rows)
    
    pdf.section_title('Performance by Confidence Tier')
    headers = ['Tier', 'Confidence Range', 'Precision', 'Recall']
    rows = [
        ['HIGH', '>=0.85', '78%', '92%'],
        ['MEDIUM', '0.65-0.85', '65%', '85%'],
        ['REVIEW', '0.50-0.65', '45%', '78%'],
    ]
    pdf.table(headers, rows)
    
    pdf.section_title('Baseline Comparison')
    headers = ['Metric', 'Baseline (Annual Audit)', 'VidyutDrishti', 'Improvement']
    rows = [
        ['Detection Time', '6-12 months', '<10 days', '95% faster'],
        ['False Positive Rate', '40-50%', '<15%', '3x reduction'],
        ['Revenue Recovery', 'Rs. 200 Cr/yr', 'Rs. 455 Cr/yr (1.5% prevalence)', '2.3x increase'],
        ['Inspection Efficiency', 'Random sampling', 'Prioritised by Rs.', '40% time saved'],
    ]
    pdf.table(headers, rows, col_widths=[2.5, 2.5, 3, 2])
    
    # Section 8: Deployment
    pdf.add_page()
    pdf.chapter_title('Deployment', '8')
    pdf.section_title('Docker Stack')
    pdf.body_text(
        'The system is packaged as a Docker Compose stack for easy deployment '
        'in BESCOM data centre infrastructure.'
    )
    
    components = [
        'timescaledb: TimescaleDB 2.11 with hypervisor extension',
        'backend: FastAPI with Python 3.11, detection and forecasting engines',
        'frontend: React 18 with Vite, served by Nginx',
    ]
    pdf.bullet_list(components)
    
    pdf.section_title('Compliance & Security')
    compliance = [
        'Read-only architecture: Zero writes to AMI/SCADA/MDM/billing',
        'No consumer PII: Only meter_id, kWh, voltage, PF processed',
        'Auditable decisions: Deterministic rule trace per flag',
        'Inspector in the loop: No automated disconnections',
        'CEA compliant: Aligns with CEA regulations for theft detection',
    ]
    pdf.bullet_list(compliance)
    
    # Section 9: Resource Requirements
    pdf.add_page()
    pdf.chapter_title('Resource Requirements', '9')
    pdf.section_title('Production Scale (BESCOM)')
    headers = ['Component', 'CPU', 'RAM', 'Storage', 'Notes']
    rows = [
        ['TimescaleDB', '16 cores', '64 GB', '2 TB SSD', 'Hypertables, 30-day retention'],
        ['Backend API', '8 cores', '32 GB', '100 GB SSD', 'Detection, forecasting, queue generation'],
        ['Frontend', '4 cores', '16 GB', '50 GB SSD', 'Nginx serving static assets'],
        ['Monitoring', '2 cores', '8 GB', '50 GB SSD', 'Prometheus, Grafana, logs'],
    ]
    pdf.table(headers, rows, col_widths=[2.5, 1.5, 1.5, 2, 4])
    
    pdf.section_title('Network Requirements')
    network = [
        'AMI/MDM API connectivity (read-only)',
        'Internal network latency <10ms between components',
        'Outbound internet access for demo video hosting (optional)',
        'HTTPS/TLS for all dashboard access',
    ]
    pdf.bullet_list(network)
    
    pdf.section_title('Scalability')
    pdf.body_text(
        'The system scales horizontally: additional backend instances can be '
        'added to handle increased detection load. TimescaleDB supports '
        'distributed deployment for multi-region scenarios.'
    )
    
    # Appendix
    pdf.add_page()
    pdf.chapter_title('Appendix: API Endpoints', 'A')
    headers = ['Endpoint', 'Method', 'Description']
    rows = [
        ['/api/v1/ingest/batch', 'POST', 'Ingest meter readings batch'],
        ['/api/v1/meters/{meter_id}/status', 'GET', '4-layer detection status + confidence'],
        ['/api/v1/queue/daily', 'GET', 'Prioritized inspection queue (Rs. x confidence)'],
        ['/api/v1/forecast/{feeder_id}', 'GET', '24-hour seasonal baseline forecast'],
        ['/api/v1/zones/summary', 'GET', 'Per-zone risk aggregation for heatmap'],
        ['/api/v1/feedback', 'POST', 'Inspector feedback (triggers live refresh)'],
        ['/api/v1/metrics/evaluation', 'GET', 'Live precision, recall, F1, detection lag'],
        ['/api/v1/metrics/roi', 'GET', 'BESCOM-scale ROI projection (interactive)'],
    ]
    pdf.table(headers, rows, col_widths=[4.5, 1.5, 4])
    
    # Appendix: Development Practices
    pdf.add_page()
    pdf.chapter_title('Development Practices & Code Quality', 'B')
    
    pdf.section_title('Testing Infrastructure')
    testing = [
        'run_prototype.py: Full system demo without Docker dependencies',
        'test_api.py: API testing script with real algorithm computation',
        'tests/e2e/test_end_to_end.py: End-to-end integration tests',
        'Per-feature test logs in logs/NN-feature-name/tests/ for validation',
    ]
    pdf.bullet_list(testing)
    
    pdf.section_title('Configuration Management')
    config = [
        'config.py: Pydantic-settings with feature flags (enable_recalibration)',
        'simulator/config.yaml: All parameters exposed (no magic numbers)',
        'Environment-based configuration with .env files',
        'Deterministic seed in simulator for reproducibility',
    ]
    pdf.bullet_list(config)
    
    pdf.section_title('Cross-Platform Development')
    cross_platform = [
        'Makefile with targets: up, down, reset, seed, lint, test, logs',
        'Works on Linux/macOS and Git Bash/WSL on Windows',
        'Linting: ruff, black, mypy (backend); eslint (frontend)',
    ]
    pdf.bullet_list(cross_platform)
    
    pdf.section_title('Implementation Patterns')
    patterns = [
        'Deterministic seed in simulator for reproducibility',
        'Ground-truth separation: injected events in separate file',
        'Idempotent upserts with ON CONFLICT DO NOTHING',
        'Continuous aggregates in TimescaleDB for hourly/daily data',
        'Seasonal Baseline Forecasting: STL decomposition + Indian holidays + lag regressors',
        'Table-driven classification: adding new classes requires only config change',
        'Append-only audit logging for all flags and decisions',
    ]
    pdf.bullet_list(patterns)
    
    pdf.section_title('Documentation Generation')
    docs = [
        'build_ppt.py: Automated PPT generation with 16 slides',
        'generate_custom_doc.py: Custom technical document generator with PDF output',
        'docs/features.md: 449-line detailed implementation order for all 22 features',
        'logs/ directory: Per-feature implementation logs with test reviews',
    ]
    pdf.bullet_list(docs)
    
    # Save
    output_path = 'VidyutDrishti_Custom_Document.pdf'
    pdf.output(output_path)
    print(f'Generated: {output_path}')

if __name__ == '__main__':
    generate_document()
