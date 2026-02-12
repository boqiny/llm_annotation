import json
import matplotlib.pyplot as plt
import pandas as pd


def load_results(dataset_name):
    """Load evaluation results for a dataset."""
    path = f"./results/{dataset_name}_self_disclosure_eval_results.json"
    with open(path, 'r') as f:
        data = json.load(f)
    return data['metrics']


def create_comparison_table():
    """Create a comparison table of all three datasets."""
    
    # Load data
    fiona_metrics = load_results('fiona')
    chang_metrics = load_results('chang')
    agreed_metrics = load_results('agreed')
    
    # Build table
    rows = []
    for scheme in sorted(fiona_metrics.keys()):
        fiona = fiona_metrics.get(scheme, {})
        chang = chang_metrics.get(scheme, {})
        agreed = agreed_metrics.get(scheme, {})
        
        rows.append({
            'Scheme': scheme,
            'Fiona Acc': f"{fiona.get('accuracy', 0):.3f}",
            'Fiona n': fiona.get('n', 0),
            'Chang Acc': f"{chang.get('accuracy', 0):.3f}",
            'Chang n': chang.get('n', 0),
            'Agreed Acc': f"{agreed.get('accuracy', 0):.3f}",
            'Agreed n': agreed.get('n', 0),
        })
    
    df = pd.DataFrame(rows)
    
    # Print table
    print("=" * 120)
    print("EVALUATION RESULTS COMPARISON")
    print("=" * 120)
    print(df.to_string(index=False))
    print("=" * 120)
    
    return df


def create_comparison_figure():
    """Create a simple bar chart comparing accuracies."""
    
    # Load data
    fiona_metrics = load_results('fiona')
    chang_metrics = load_results('chang')
    agreed_metrics = load_results('agreed')
    
    # Extract data
    schemes = sorted(fiona_metrics.keys())
    fiona_acc = [fiona_metrics[s]['accuracy'] for s in schemes]
    chang_acc = [chang_metrics[s]['accuracy'] for s in schemes]
    agreed_acc = [agreed_metrics[s]['accuracy'] for s in schemes]
    
    # Create figure
    fig, ax = plt.subplots(figsize=(10, 6))
    
    x = range(len(schemes))
    width = 0.25
    
    ax.bar([i - width for i in x], fiona_acc, width, label='Fiona', alpha=0.8)
    ax.bar(x, chang_acc, width, label='Chang', alpha=0.8)
    ax.bar([i + width for i in x], agreed_acc, width, label='Agreed', alpha=0.8)
    
    ax.set_xlabel('Scheme', fontsize=12)
    ax.set_ylabel('Accuracy', fontsize=12)
    ax.set_title('LLM Annotation Accuracy by Dataset and Scheme', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels([s.replace(' ', '\n') for s in schemes], fontsize=9)
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3)
    ax.set_ylim(0, 1)
    
    plt.tight_layout()
    plt.savefig('./results/evaluation_comparison.png', dpi=300, bbox_inches='tight')
    print("\nFigure saved to: ./results/evaluation_comparison.png")
    plt.close()


if __name__ == "__main__":
    create_comparison_table()
    create_comparison_figure()
