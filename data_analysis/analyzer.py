"""
Data Analysis Module for JRVS

Provides data analysis capabilities including:
- CSV/Excel file loading and analysis
- Data querying and statistics
- AI-powered insights
- Jupyter notebook integration
"""

from typing import Dict, List, Optional, Any
from pathlib import Path

# Optional pandas import - gracefully handle if not installed
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    pd = None
    PANDAS_AVAILABLE = False


class DataAnalyzer:
    """Data analysis and visualization engine for JRVS"""

    def __init__(self):
        self.loaded_datasets: Dict[str, Any] = {}
        self.loaded_notebooks: Dict[str, Any] = {}

    async def load_csv(self, file_path: str, name: Optional[str] = None) -> Dict[str, Any]:
        """Load and analyze a CSV file"""
        if not PANDAS_AVAILABLE:
            return {"success": False, "error": "pandas not installed. Run: pip install pandas"}
        
        try:
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}"}
            
            dataset_name = name or path.stem
            df = pd.read_csv(file_path)
            self.loaded_datasets[dataset_name] = df
            
            return {
                "success": True,
                "name": dataset_name,
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": list(df.columns),
                "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()}
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def load_excel(self, file_path: str, sheet_name: Optional[str] = None, 
                        name: Optional[str] = None) -> Dict[str, Any]:
        """Load and analyze an Excel file"""
        if not PANDAS_AVAILABLE:
            return {"success": False, "error": "pandas not installed. Run: pip install pandas"}
        
        try:
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}"}
            
            dataset_name = name or path.stem
            df = pd.read_excel(file_path, sheet_name=sheet_name)
            self.loaded_datasets[dataset_name] = df
            
            return {
                "success": True,
                "name": dataset_name,
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": list(df.columns),
                "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()}
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_datasets(self) -> Dict[str, Any]:
        """List all loaded datasets"""
        return {
            "datasets": [
                {
                    "name": name,
                    "rows": len(df) if hasattr(df, '__len__') else 0,
                    "columns": len(df.columns) if hasattr(df, 'columns') else 0
                }
                for name, df in self.loaded_datasets.items()
            ]
        }

    async def query_data(self, dataset_name: str, query: str, limit: int = 100) -> Dict[str, Any]:
        """
        Execute a filter query on a dataset using column-based filtering.
        
        Note: For security, this uses explicit column filtering instead of pandas.query()
        which could execute arbitrary Python code.
        
        Args:
            dataset_name: Name of the loaded dataset
            query: Filter expression in format "column operator value" (e.g., "age > 25")
            limit: Maximum rows to return (default 100)
        """
        if dataset_name not in self.loaded_datasets:
            return {"success": False, "error": f"Dataset '{dataset_name}' not found"}
        
        if not PANDAS_AVAILABLE:
            return {"success": False, "error": "pandas not installed"}
        
        try:
            df = self.loaded_datasets[dataset_name]
            
            # Parse simple filter expressions safely
            # Support: column == value, column > value, column < value, etc.
            import re
            match = re.match(r'^\s*(\w+)\s*(==|!=|>|<|>=|<=)\s*(.+)\s*$', query)
            
            if match:
                column, operator, value = match.groups()
                
                if column not in df.columns:
                    return {"success": False, "error": f"Column '{column}' not found"}
                
                # Try to convert value to appropriate type
                value = value.strip().strip('"\'')
                try:
                    if df[column].dtype.kind in 'iufc':  # numeric types
                        value = float(value)
                except (ValueError, TypeError):
                    pass
                
                # Apply filter using safe operations
                if operator == '==':
                    result = df[df[column] == value]
                elif operator == '!=':
                    result = df[df[column] != value]
                elif operator == '>':
                    result = df[df[column] > value]
                elif operator == '<':
                    result = df[df[column] < value]
                elif operator == '>=':
                    result = df[df[column] >= value]
                elif operator == '<=':
                    result = df[df[column] <= value]
                else:
                    return {"success": False, "error": f"Unsupported operator: {operator}"}
            else:
                # If no valid filter, return all data
                result = df
            
            return {
                "success": True,
                "rows": len(result),
                "data": result.head(limit).to_dict('records')
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_column_stats(self, dataset_name: str, column_name: str) -> Dict[str, Any]:
        """Get statistics for a specific column"""
        if dataset_name not in self.loaded_datasets:
            return {"success": False, "error": f"Dataset '{dataset_name}' not found"}
        
        try:
            df = self.loaded_datasets[dataset_name]
            if column_name not in df.columns:
                return {"success": False, "error": f"Column '{column_name}' not found"}
            
            col = df[column_name]
            stats = {
                "name": column_name,
                "dtype": str(col.dtype),
                "count": int(col.count()),
                "null_count": int(col.isnull().sum()),
                "unique_count": int(col.nunique())
            }
            
            # Add numeric stats if applicable
            if col.dtype.kind in 'iufc':  # integer, unsigned, float, complex
                stats.update({
                    "mean": float(col.mean()) if not col.empty else None,
                    "std": float(col.std()) if not col.empty else None,
                    "min": float(col.min()) if not col.empty else None,
                    "max": float(col.max()) if not col.empty else None,
                    "median": float(col.median()) if not col.empty else None
                })
            
            return {"success": True, "stats": stats}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_ai_insights(self, dataset_name: str, jarcore: Any) -> Dict[str, Any]:
        """Get AI-powered insights about the dataset"""
        if dataset_name not in self.loaded_datasets:
            return {"success": False, "error": f"Dataset '{dataset_name}' not found"}
        
        try:
            df = self.loaded_datasets[dataset_name]
            
            # Create a summary of the dataset
            summary = f"""Dataset: {dataset_name}
Rows: {len(df)}
Columns: {len(df.columns)}
Column info:
{df.dtypes.to_string()}

Sample data:
{df.head(5).to_string()}

Basic statistics:
{df.describe().to_string() if not df.empty else 'No data'}
"""
            
            # Use JARCORE to generate insights
            result = await jarcore.generate_code(
                task=f"Analyze this dataset and provide key insights:\n{summary}",
                language="text",
                include_tests=False
            )
            
            return {"success": True, "insights": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def create_jupyter_notebook(self, name: str, title: str = "New Notebook") -> Dict[str, Any]:
        """Create a new Jupyter notebook"""
        try:
            notebook = {
                "cells": [
                    {
                        "cell_type": "markdown",
                        "metadata": {},
                        "source": [f"# {title}\n", "\nCreated by JRVS Data Analysis"]
                    },
                    {
                        "cell_type": "code",
                        "execution_count": None,
                        "metadata": {},
                        "outputs": [],
                        "source": ["import pandas as pd\nimport numpy as np\nimport matplotlib.pyplot as plt"]
                    }
                ],
                "metadata": {
                    "kernelspec": {
                        "display_name": "Python 3",
                        "language": "python",
                        "name": "python3"
                    }
                },
                "nbformat": 4,
                "nbformat_minor": 4
            }
            
            self.loaded_notebooks[name] = notebook
            return {"success": True, "name": name, "title": title}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def load_jupyter_notebook(self, file_path: str) -> Dict[str, Any]:
        """Load a Jupyter notebook from file"""
        try:
            import json
            
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}"}
            
            with open(path, 'r') as f:
                notebook = json.load(f)
            
            name = path.stem
            self.loaded_notebooks[name] = notebook
            
            return {
                "success": True,
                "name": name,
                "cells": len(notebook.get("cells", []))
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_notebooks(self) -> Dict[str, Any]:
        """List all loaded notebooks"""
        return {
            "notebooks": [
                {
                    "name": name,
                    "cells": len(nb.get("cells", []))
                }
                for name, nb in self.loaded_notebooks.items()
            ]
        }


# Global data analyzer instance
data_analyzer = DataAnalyzer()
