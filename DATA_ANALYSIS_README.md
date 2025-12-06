# JRVS Data Analysis Lab

AI-powered data analysis partner integrated into JRVS web interface.

## Features

### 📊 **CSV/Excel Analysis**
- Upload and analyze CSV and Excel files
- Interactive data table viewer (Excel-like interface)
- Real-time data statistics
- Column-level analysis
- Missing value detection
- Data type inference

### 🔍 **Smart Querying**
- Pandas-style queries: `Age > 30 and City == 'NYC'`
- Filter and explore data interactively
- Export query results

### 💡 **AI-Powered Insights (JARCORE)**
- Automatic data quality assessment
- AI-generated insights about your data
- Suggested analyses and visualizations
- Python code generation for complex analyses
- Anomaly detection suggestions

### 📓 **Jupyter Notebook Integration**
- Create and edit Jupyter notebooks
- View notebook cells (code, markdown, outputs)
- Execute cells and see results
- Perfect for data exploration

## Usage

### Access the Data Analysis Lab

1. Start JRVS web server:
```bash
cd /home/xmanz/JRVS
python3 web_server.py
```

2. Open in browser:
```
http://[your-tailscale-ip]:8080/data_analysis.html
```

3. Click "📊 Data Analysis Lab" in the sidebar

### Load a Dataset

**Option 1: File Path**
```
1. Enter file path in the text box
2. Click "Load File"
```

**Option 2: Upload** (coming soon)
```
1. Click "Upload CSV/Excel"
2. Select file from your computer
```

### Analyze Data

1. **View Data**: Browse your dataset in Excel-like table
2. **Run Queries**: Filter data with pandas syntax
3. **Get AI Insights**: Let JARCORE analyze and suggest insights
4. **Create Notebooks**: Build analyses in Jupyter notebooks

### Example Workflow

```python
# 1. Load dataset
Load: /home/xmanz/data/sales.csv

# 2. Explore with queries
Query: "Revenue > 10000 and Region == 'West'"

# 3. Get AI insights
Click "Generate Insights"
→ JARCORE analyzes data quality
→ Suggests visualizations
→ Generates analysis code

# 4. Create notebook for deeper analysis
Click "New Notebook"
→ Use JARCORE-generated code
→ Build custom visualizations
→ Document findings
```

## API Endpoints

### Data Endpoints

```python
# Load CSV
POST /api/data/upload/csv
Body: {"file_path": "/path/to/file.csv", "name": "optional_name"}

# Load Excel
POST /api/data/upload/excel
Body: {"file_path": "/path/to/file.xlsx", "sheet_name": "Sheet1"}

# List datasets
GET /api/data/datasets

# Get dataset info
GET /api/data/dataset/{dataset_name}

# Query dataset
POST /api/data/query
Body: {"dataset_name": "my_data", "query": "Age > 30"}

# Get column statistics
GET /api/data/column/{dataset_name}/{column_name}

# Get AI insights
POST /api/data/ai-insights/{dataset_name}
```

### Notebook Endpoints

```python
# Create notebook
POST /api/notebook/create
Body: {"name": "analysis", "title": "My Analysis"}

# Load notebook
POST /api/notebook/load
Body: {"file_path": "/path/to/notebook.ipynb"}

# List notebooks
GET /api/notebook/list
```

## Supported File Formats

- **CSV**: `.csv`
- **Excel**: `.xlsx`, `.xls`
- **Jupyter Notebooks**: `.ipynb`

## Data Analysis Features

### Automatic Statistics

For every dataset, JRVS calculates:
- Row/column counts
- Data types
- Missing values
- Memory usage
- Numeric statistics (min, max, mean, median, std)
- Categorical distributions

### AI-Powered Insights

JARCORE analyzes your data and provides:

1. **Data Quality Assessment**
   - Missing value patterns
   - Data type inconsistencies
   - Outlier detection

2. **Suggested Analyses**
   - Correlation analysis
   - Time series patterns
   - Grouping and aggregation ideas

3. **Visualization Recommendations**
   - Appropriate chart types
   - Key variables to visualize
   - Interactive dashboard ideas

4. **Code Generation**
   - Python code for suggested analyses
   - Pandas/NumPy operations
   - Matplotlib/Seaborn visualizations

### Query Examples

```python
# Simple filter
"Age > 25"

# Multiple conditions
"Age > 25 and Salary < 100000"

# String matching
"City == 'New York' or City == 'Boston'"

# Numeric ranges
"Price >= 10 and Price <= 50"

# Null checks
"Email.isnull()"
```

## Jupyter Notebook Features

- **Create** new notebooks from scratch
- **Load** existing `.ipynb` files
- **View** cells with syntax highlighting
- **Execute** code cells (coming soon)
- **Export** analyses and visualizations

## Integration with JARCORE

The Data Analysis Lab uses JARCORE (JARVIS Autonomous Reasoning & Coding Engine) for:

- **Intelligent analysis**: Understanding your data context
- **Code generation**: Creating analysis scripts
- **Insight discovery**: Finding patterns automatically
- **Visualization**: Suggesting and generating charts
- **Documentation**: Auto-documenting analyses

## Requirements

```bash
pip install pandas openpyxl nbformat
```

- `pandas`: Data manipulation
- `openpyxl`: Excel file support
- `nbformat`: Jupyter notebook support

## Tips

1. **Start small**: Load a sample dataset first to understand the interface
2. **Use AI insights**: Let JARCORE suggest analyses before diving in
3. **Query iteratively**: Start with simple queries, then refine
4. **Document in notebooks**: Use notebooks to build reproducible analyses
5. **Check data quality**: Always review statistics before analysis

## Roadmap

- [ ] File upload via web interface
- [ ] Execute Jupyter notebook cells
- [ ] Export to PDF/HTML
- [ ] Real-time visualizations (charts/graphs)
- [ ] Data transformations (pivot, merge, groupby)
- [ ] SQL query support
- [ ] Scheduled data refreshes
- [ ] Collaborative notebooks
- [ ] Version control for datasets

## Architecture

```
Data Analysis Lab
├── Frontend (data_analysis.html)
│   ├── Dataset browser
│   ├── Excel-like table viewer
│   ├── Query interface
│   └── Notebook viewer
├── Backend (data_analysis/analyzer.py)
│   ├── DataAnalyzer class
│   ├── Pandas operations
│   └── Jupyter integration
└── AI Layer (JARCORE)
    ├── Code generation
    ├── Insight discovery
    └── Analysis suggestions
```

## Example Use Cases

### 1. Sales Analysis
```
Load: sales_data.csv
Query: "Revenue > avg_revenue and Quarter == 'Q4'"
AI Insight: "Strong Q4 performance, suggest analyzing by product category"
```

### 2. Customer Segmentation
```
Load: customers.xlsx
AI Insight: "Detect 3 distinct customer segments by purchase behavior"
Generate: K-means clustering code
```

### 3. Data Cleaning
```
Load: raw_data.csv
AI Insight: "15% missing values in 'Email' column, suggest imputation strategy"
Query: "Email.notnull()"
```

### 4. Time Series Analysis
```
Load: stock_prices.csv
AI Insight: "Detect seasonality patterns, suggest ARIMA model"
Notebook: Build forecasting model
```

## Privacy & Security

✅ **All data stays local** - No external API calls
✅ **Tailscale only** - Accessible only on your private network
✅ **No data persistence** - Datasets cleared on server restart
✅ **Safe execution** - Queries run in sandboxed environment

---

**JRVS Data Analysis Lab** - Turn JARVIS into your personal data scientist! 📊🤖
