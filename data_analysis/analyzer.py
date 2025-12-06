"""
Data Analysis Engine for JRVS

Provides CSV/Excel analysis, Jupyter notebook integration, and AI-powered data insights
using JARCORE for automated analysis and visualization suggestions.
"""

import pandas as pd
import json
import io
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import base64

# For Jupyter notebook handling
try:
    import nbformat
    from nbformat import v4 as nbf
    JUPYTER_AVAILABLE = True
except ImportError:
    JUPYTER_AVAILABLE = False
    print("Warning: nbformat not installed. Jupyter features disabled.")


class DataAnalyzer:
    """Analyzes CSV/Excel files and Jupyter notebooks"""

    def __init__(self, workspace_dir: str = "/home/xmanz/JRVS/data"):
        self.workspace = Path(workspace_dir)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.loaded_datasets: Dict[str, pd.DataFrame] = {}
        self.notebooks: Dict[str, Any] = {}

    async def load_csv(self, file_path: str, name: Optional[str] = None) -> Dict[str, Any]:
        """
        Load CSV file and return metadata + preview

        Args:
            file_path: Path to CSV file
            name: Optional name for the dataset

        Returns:
            Dictionary with dataset info and preview
        """
        try:
            # Read CSV
            df = pd.read_csv(file_path)

            # Generate name if not provided
            if not name:
                name = Path(file_path).stem

            # Store dataset
            self.loaded_datasets[name] = df

            # Generate metadata
            metadata = {
                "name": name,
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": list(df.columns),
                "column_types": {col: str(dtype) for col, dtype in df.dtypes.items()},
                "memory_usage": f"{df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB",
                "missing_values": df.isnull().sum().to_dict(),
                "loaded_at": datetime.now().isoformat()
            }

            # Generate preview (first 10 rows)
            preview = df.head(10).to_dict('records')

            # Basic statistics
            stats = {}
            numeric_cols = df.select_dtypes(include=['number']).columns
            if len(numeric_cols) > 0:
                stats = df[numeric_cols].describe().to_dict()

            return {
                "success": True,
                "metadata": metadata,
                "preview": preview,
                "statistics": stats
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def load_excel(self, file_path: str, sheet_name: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
        """Load Excel file"""
        try:
            # Read Excel
            if sheet_name:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
            else:
                df = pd.read_excel(file_path)

            # Generate name
            if not name:
                name = Path(file_path).stem
                if sheet_name:
                    name = f"{name}_{sheet_name}"

            # Store dataset
            self.loaded_datasets[name] = df

            # Get sheet names
            xl = pd.ExcelFile(file_path)
            sheet_names = xl.sheet_names

            # Generate metadata (same as CSV)
            metadata = {
                "name": name,
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": list(df.columns),
                "column_types": {col: str(dtype) for col, dtype in df.dtypes.items()},
                "memory_usage": f"{df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB",
                "missing_values": df.isnull().sum().to_dict(),
                "sheet_names": sheet_names,
                "current_sheet": sheet_name or sheet_names[0],
                "loaded_at": datetime.now().isoformat()
            }

            preview = df.head(10).to_dict('records')

            # Statistics
            stats = {}
            numeric_cols = df.select_dtypes(include=['number']).columns
            if len(numeric_cols) > 0:
                stats = df[numeric_cols].describe().to_dict()

            return {
                "success": True,
                "metadata": metadata,
                "preview": preview,
                "statistics": stats
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def query_data(self, dataset_name: str, query: str) -> Dict[str, Any]:
        """
        Execute pandas query on dataset

        Args:
            dataset_name: Name of loaded dataset
            query: Pandas query string (e.g., "Age > 30 and City == 'NYC'")
        """
        try:
            if dataset_name not in self.loaded_datasets:
                return {"success": False, "error": f"Dataset '{dataset_name}' not loaded"}

            df = self.loaded_datasets[dataset_name]

            # Execute query
            result_df = df.query(query)

            return {
                "success": True,
                "rows_returned": len(result_df),
                "data": result_df.head(100).to_dict('records')  # Limit to 100 rows
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def get_column_stats(self, dataset_name: str, column_name: str) -> Dict[str, Any]:
        """Get detailed statistics for a specific column"""
        try:
            if dataset_name not in self.loaded_datasets:
                return {"success": False, "error": f"Dataset '{dataset_name}' not loaded"}

            df = self.loaded_datasets[dataset_name]

            if column_name not in df.columns:
                return {"success": False, "error": f"Column '{column_name}' not found"}

            col = df[column_name]

            stats = {
                "column": column_name,
                "type": str(col.dtype),
                "count": int(col.count()),
                "unique": int(col.nunique()),
                "missing": int(col.isnull().sum()),
                "missing_percent": f"{(col.isnull().sum() / len(df) * 100):.2f}%"
            }

            # Numeric stats
            if pd.api.types.is_numeric_dtype(col):
                stats.update({
                    "min": float(col.min()) if not pd.isna(col.min()) else None,
                    "max": float(col.max()) if not pd.isna(col.max()) else None,
                    "mean": float(col.mean()) if not pd.isna(col.mean()) else None,
                    "median": float(col.median()) if not pd.isna(col.median()) else None,
                    "std": float(col.std()) if not pd.isna(col.std()) else None,
                    "quartiles": {
                        "25%": float(col.quantile(0.25)) if not pd.isna(col.quantile(0.25)) else None,
                        "50%": float(col.quantile(0.50)) if not pd.isna(col.quantile(0.50)) else None,
                        "75%": float(col.quantile(0.75)) if not pd.isna(col.quantile(0.75)) else None
                    }
                })

            # Categorical stats
            if pd.api.types.is_string_dtype(col) or pd.api.types.is_categorical_dtype(col):
                value_counts = col.value_counts().head(10).to_dict()
                stats["top_values"] = value_counts

            return {
                "success": True,
                "statistics": stats
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def create_jupyter_notebook(self, name: str, title: str = "New Notebook") -> Dict[str, Any]:
        """Create a new Jupyter notebook"""
        if not JUPYTER_AVAILABLE:
            return {"success": False, "error": "Jupyter support not available"}

        try:
            # Create new notebook
            nb = nbf.new_notebook()

            # Add title cell
            nb.cells.append(nbf.new_markdown_cell(f"# {title}\n\nCreated by JRVS"))

            # Add code cell
            nb.cells.append(nbf.new_code_cell("# Start coding here\nimport pandas as pd\nimport numpy as np\nimport matplotlib.pyplot as plt"))

            # Store notebook
            self.notebooks[name] = nb

            # Save to file
            notebook_path = self.workspace / f"{name}.ipynb"
            with open(notebook_path, 'w') as f:
                nbformat.write(nb, f)

            return {
                "success": True,
                "name": name,
                "path": str(notebook_path),
                "cells": len(nb.cells)
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def load_jupyter_notebook(self, file_path: str) -> Dict[str, Any]:
        """Load and parse Jupyter notebook"""
        if not JUPYTER_AVAILABLE:
            return {"success": False, "error": "Jupyter support not available"}

        try:
            with open(file_path, 'r') as f:
                nb = nbformat.read(f, as_version=4)

            name = Path(file_path).stem
            self.notebooks[name] = nb

            # Extract cells
            cells = []
            for idx, cell in enumerate(nb.cells):
                cell_data = {
                    "index": idx,
                    "cell_type": cell.cell_type,
                    "source": cell.source,
                    "metadata": cell.metadata
                }

                # Add execution info for code cells
                if cell.cell_type == 'code':
                    cell_data["execution_count"] = cell.execution_count
                    if cell.outputs:
                        cell_data["outputs"] = [self._format_output(output) for output in cell.outputs]

                cells.append(cell_data)

            return {
                "success": True,
                "name": name,
                "cells": cells,
                "metadata": nb.metadata
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _format_output(self, output) -> Dict[str, Any]:
        """Format Jupyter notebook output for web display"""
        output_data = {
            "output_type": output.output_type
        }

        if output.output_type == 'stream':
            output_data["text"] = output.text
        elif output.output_type == 'execute_result' or output.output_type == 'display_data':
            if 'text/plain' in output.data:
                output_data["text"] = output.data['text/plain']
            if 'text/html' in output.data:
                output_data["html"] = output.data['text/html']
            if 'image/png' in output.data:
                output_data["image"] = output.data['image/png']
        elif output.output_type == 'error':
            output_data["error"] = {
                "ename": output.ename,
                "evalue": output.evalue,
                "traceback": output.traceback
            }

        return output_data

    async def get_ai_insights(self, dataset_name: str, jarcore) -> Dict[str, Any]:
        """
        Use JARCORE to generate insights about the dataset

        Args:
            dataset_name: Name of dataset to analyze
            jarcore: JARCORE instance for AI analysis
        """
        try:
            if dataset_name not in self.loaded_datasets:
                return {"success": False, "error": f"Dataset '{dataset_name}' not loaded"}

            df = self.loaded_datasets[dataset_name]

            # Create summary for AI
            summary = f"""Dataset: {dataset_name}
Rows: {len(df)}
Columns: {len(df.columns)}

Column Information:
"""
            for col in df.columns:
                summary += f"- {col} ({df[col].dtype}): {df[col].nunique()} unique values, {df[col].isnull().sum()} missing\n"

            # Add sample data
            summary += f"\nFirst few rows:\n{df.head(3).to_string()}\n"

            # Ask JARCORE for analysis suggestions
            prompt = f"""Analyze this dataset and provide:
1. Key insights about the data
2. Potential data quality issues
3. Suggested analyses or visualizations
4. Python code for interesting analyses

{summary}
"""

            analysis = await jarcore.generate_code(
                task=prompt,
                language="python",
                context=summary,
                include_tests=False
            )

            return {
                "success": True,
                "insights": analysis.get("explanation", ""),
                "suggested_code": analysis.get("code", ""),
                "dependencies": analysis.get("dependencies", [])
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def list_datasets(self) -> Dict[str, Any]:
        """List all loaded datasets"""
        datasets = []
        for name, df in self.loaded_datasets.items():
            datasets.append({
                "name": name,
                "rows": len(df),
                "columns": len(df.columns),
                "memory_mb": f"{df.memory_usage(deep=True).sum() / 1024 / 1024:.2f}"
            })

        return {
            "count": len(datasets),
            "datasets": datasets
        }

    def list_notebooks(self) -> Dict[str, Any]:
        """List all loaded notebooks"""
        notebooks = []
        for name, nb in self.notebooks.items():
            notebooks.append({
                "name": name,
                "cells": len(nb.cells)
            })

        return {
            "count": len(notebooks),
            "notebooks": notebooks
        }


# Global data analyzer instance
data_analyzer = DataAnalyzer()
