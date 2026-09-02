import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applyNotebookCodeCellAction,
  sha256Source,
  type BridgeCell,
  type CellMetadata,
  type NewCodeCell,
  type NotebookBridgeModel,
  type NotebookCodeCellAction
} from '../src/notebook_action.ts';


class MockCell implements BridgeCell {
  readonly id: string;
  readonly type: string;
  source: string;
  metadata: Record<string, unknown>;
  executionCount: number | null;
  outputs: unknown[];

  constructor(options: {
    id: string;
    type: string;
    source: string;
    metadata?: Record<string, unknown>;
    executionCount?: number | null;
    outputs?: unknown[];
  }) {
    this.id = options.id;
    this.type = options.type;
    this.source = options.source;
    this.metadata = { ...(options.metadata ?? {}) };
    this.executionCount = options.executionCount ?? null;
    this.outputs = [...(options.outputs ?? [])];
  }

  getSource(): string {
    return this.source;
  }

  setSource(source: string): void {
    this.source = source;
  }

  setMetadata(metadata: CellMetadata): void {
    Object.assign(this.metadata, metadata);
  }

  clone(): MockCell {
    return new MockCell({
      id: this.id,
      type: this.type,
      source: this.source,
      metadata: this.metadata,
      executionCount: this.executionCount,
      outputs: this.outputs
    });
  }
}


class MockNotebook implements NotebookBridgeModel {
  readonly path = 'notebooks/analysis.ipynb';
  readonly readOnly = false;
  cells: MockCell[];
  activeCellIndex: number;
  saveCount = 0;
  transactionCount = 0;
  saveError: Error | null = null;
  private undoStack: MockCell[][] = [];

  constructor(cells: MockCell[], activeCellIndex: number) {
    this.cells = cells;
    this.activeCellIndex = activeCellIndex;
  }

  transact(change: () => void): void {
    const before = this.cells.map(cell => cell.clone());
    change();
    this.undoStack.push(before);
    this.transactionCount += 1;
  }

  insertCodeCell(index: number, cell: NewCodeCell): void {
    this.cells.splice(
      index,
      0,
      new MockCell({
        id: cell.id,
        type: cell.cell_type,
        source: cell.source,
        metadata: cell.metadata,
        executionCount: cell.execution_count,
        outputs: cell.outputs
      })
    );
  }

  setActiveCellIndex(index: number): void {
    this.activeCellIndex = index;
  }

  async save(): Promise<void> {
    this.saveCount += 1;

    if (this.saveError) {
      throw this.saveError;
    }
  }

  undo(): void {
    const previous = this.undoStack.pop();

    if (previous) {
      this.cells = previous;
    }
  }
}


function action(
  overrides: Partial<NotebookCodeCellAction>
): NotebookCodeCellAction {
  return {
    action_id: 'action-1',
    type: 'write_jupyter_code_cell',
    task_id: 'task-1',
    notebook_path: 'notebooks/analysis.ipynb',
    mode: 'create',
    source: 'print("new")',
    target_cell_id: null,
    expected_source_hash: null,
    ...overrides
  };
}


test('revise는 원본을 유지하고 대상 바로 아래에 새 code cell을 만든다', async () => {
  const target = new MockCell({
    id: 'target-cell',
    type: 'code',
    source: 'def old():\n    return 1',
    executionCount: 7,
    outputs: [{ output_type: 'stream', text: 'old' }]
  });
  const notebook = new MockNotebook(
    [target, new MockCell({ id: 'next', type: 'markdown', source: '# Next' })],
    0
  );
  const sourceHash = await sha256Source(target.source);
  const result = await applyNotebookCodeCellAction(
    notebook,
    action({
      mode: 'revise',
      source: 'def old():\n    return 2',
      target_cell_id: target.id,
      expected_source_hash: sourceHash
    })
  );

  assert.equal(notebook.cells.length, 3);
  assert.equal(notebook.cells[0].id, 'target-cell');
  assert.equal(notebook.cells[0].source, 'def old():\n    return 1');
  assert.equal(notebook.cells[0].executionCount, 7);
  assert.deepEqual(notebook.cells[0].outputs, [
    { output_type: 'stream', text: 'old' }
  ]);
  assert.equal(notebook.cells[1].type, 'code');
  assert.equal(notebook.cells[1].source, 'def old():\n    return 2');
  assert.equal(notebook.cells[1].executionCount, null);
  assert.deepEqual(notebook.cells[1].outputs, []);
  assert.equal(notebook.cells[1].metadata.task_id, 'task-1');
  assert.equal(notebook.cells[1].metadata.operation, 'revise');
  assert.equal(notebook.cells[1].metadata.anchor_cell_id, 'target-cell');
  assert.equal(typeof notebook.cells[1].metadata.created_at, 'string');
  assert.notEqual(notebook.cells[1].id, 'target-cell');
  assert.equal(result.operation, 'revision_cell_inserted');
  assert.equal(result.cell_id, notebook.cells[1].id);
  assert.equal(result.anchor_cell_id, 'target-cell');
  assert.equal(result.executed, false);
  assert.equal(notebook.saveCount, 1);
  assert.equal(notebook.transactionCount, 1);

  notebook.undo();
  assert.equal(notebook.cells.length, 2);
  assert.equal(notebook.cells[0].source, 'def old():\n    return 1');
});


test('반복 revise는 호출자가 지정한 최신 셀 바로 아래에 만든다', async () => {
  const notebook = new MockNotebook(
    [new MockCell({ id: 'original', type: 'code', source: 'value = 1' })],
    0
  );
  const first = await applyNotebookCodeCellAction(
    notebook,
    action({
      mode: 'revise',
      source: 'value = 2',
      target_cell_id: 'original'
    })
  );
  const second = await applyNotebookCodeCellAction(
    notebook,
    action({
      action_id: 'action-2',
      mode: 'revise',
      source: 'value = 3',
      target_cell_id: first.cell_id
    })
  );

  assert.deepEqual(
    notebook.cells.map(cell => cell.source),
    ['value = 1', 'value = 2', 'value = 3']
  );
  assert.equal(second.anchor_cell_id, first.cell_id);
});


test('잘못된 cell ID와 source hash는 model을 변경하지 않는다', async () => {
  const notebook = new MockNotebook(
    [new MockCell({ id: 'target', type: 'code', source: 'value = 1' })],
    0
  );

  await assert.rejects(
    applyNotebookCodeCellAction(
      notebook,
      action({
        mode: 'revise',
        target_cell_id: 'missing'
      })
    ),
    /해당하는 셀이 없습니다/
  );
  await assert.rejects(
    applyNotebookCodeCellAction(
      notebook,
      action({
        mode: 'revise',
        target_cell_id: 'target',
        expected_source_hash: '0'.repeat(64)
      })
    ),
    /hash가 일치하지 않습니다/
  );

  assert.equal(notebook.cells.length, 1);
  assert.equal(notebook.cells[0].source, 'value = 1');
  assert.equal(notebook.transactionCount, 0);
  assert.equal(notebook.saveCount, 0);
});


test('revise는 Markdown 셀을 거부하고 model을 변경하지 않는다', async () => {
  const notebook = new MockNotebook(
    [new MockCell({ id: 'markdown', type: 'markdown', source: '# Title' })],
    0
  );

  await assert.rejects(
    applyNotebookCodeCellAction(
      notebook,
      action({
        mode: 'revise',
        target_cell_id: 'markdown'
      })
    ),
    /code cell이어야 합니다/
  );

  assert.equal(notebook.cells.length, 1);
  assert.equal(notebook.cells[0].source, '# Title');
  assert.equal(notebook.transactionCount, 0);
  assert.equal(notebook.saveCount, 0);
});


test('create는 비어 있는 활성 code cell을 그대로 사용한다', async () => {
  const empty = new MockCell({
    id: 'empty-cell',
    type: 'code',
    source: '',
    executionCount: 3,
    outputs: [{ output_type: 'display_data' }]
  });
  const notebook = new MockNotebook([empty], 0);
  const result = await applyNotebookCodeCellAction(
    notebook,
    action({ source: 'class Created:\n    pass' })
  );

  assert.equal(notebook.cells.length, 1);
  assert.equal(notebook.cells[0].id, 'empty-cell');
  assert.equal(notebook.cells[0].source, 'class Created:\n    pass');
  assert.equal(notebook.cells[0].executionCount, 3);
  assert.deepEqual(notebook.cells[0].outputs, [
    { output_type: 'display_data' }
  ]);
  assert.equal(notebook.cells[0].metadata.operation, 'create');
  assert.equal(result.operation, 'active_empty_code_cell_filled');
  assert.equal(result.cell_id, 'empty-cell');
  assert.equal(result.executed, false);
});


test('create는 내용 있는 활성 셀 바로 아래에 새 code cell을 만든다', async () => {
  const original = new MockCell({
    id: 'content-cell',
    type: 'code',
    source: 'existing = True',
    executionCount: 1,
    outputs: [{ output_type: 'execute_result' }]
  });
  const notebook = new MockNotebook([original], 0);
  const result = await applyNotebookCodeCellAction(
    notebook,
    action({ source: 'created = True' })
  );

  assert.equal(notebook.cells[0].source, 'existing = True');
  assert.equal(notebook.cells[0].executionCount, 1);
  assert.deepEqual(notebook.cells[0].outputs, [
    { output_type: 'execute_result' }
  ]);
  assert.equal(notebook.cells[1].source, 'created = True');
  assert.equal(notebook.cells[1].executionCount, null);
  assert.deepEqual(notebook.cells[1].outputs, []);
  assert.equal(result.operation, 'creation_cell_inserted');
  assert.equal(result.anchor_cell_id, 'content-cell');
});


test('create는 활성 Markdown 셀 바로 아래에 새 code cell을 만든다', async () => {
  const markdown = new MockCell({
    id: 'markdown-cell',
    type: 'markdown',
    source: '# Existing markdown'
  });
  const notebook = new MockNotebook([markdown], 0);
  const result = await applyNotebookCodeCellAction(
    notebook,
    action({ source: 'print("created")' })
  );

  assert.equal(notebook.cells[0].type, 'markdown');
  assert.equal(notebook.cells[0].source, '# Existing markdown');
  assert.equal(notebook.cells[1].type, 'code');
  assert.equal(notebook.cells[1].source, 'print("created")');
  assert.equal(result.anchor_cell_id, 'markdown-cell');
  assert.equal(result.executed, false);
});


test('저장 실패 시 transaction을 undo하고 활성 셀을 복구한다', async () => {
  const notebook = new MockNotebook(
    [new MockCell({ id: 'content-cell', type: 'code', source: 'existing = True' })],
    0
  );
  notebook.saveError = new Error('save failed');

  await assert.rejects(
    applyNotebookCodeCellAction(
      notebook,
      action({ source: 'created = True' })
    ),
    /save failed/
  );

  assert.equal(notebook.cells.length, 1);
  assert.equal(notebook.cells[0].source, 'existing = True');
  assert.equal(notebook.activeCellIndex, 0);
});
