# 統一社員番号管理アプリケーション (v1.4 仕様書実装)

`統一社員番号管理アプリケーション_仕様書_v1.4.md` に基づく実装。全体構成は
仕様書 9章のとおり: React (ブラウザ) → Apache/Nginx (本実装では省略、Docker
Composeでは直接ポート公開) → Express (Webアプリ層・薄いプロキシ) →
FastAPI (REST API・照合・採番・権限) → SQLAlchemy → PostgreSQL。

```
backend/    FastAPI + SQLAlchemy + PostgreSQL。統一社員番号の採番・照合・
            確認待ちフロー・CSV一括登録・JSONバルク登録 (spec 4, 6, 7, 8)
frontend/   React (Vite)。社員一覧・検索、個別登録、一括登録、確認待ち一覧
            (spec 5)
webapp/     Express。/api/v1 を FastAPI へプロキシし、Reactのビルド済み
            静的ファイルを配信する (spec 9.2)。社員DBへの直接アクセス・
            採番処理は実装しない。
docker-compose.yml   PostgreSQL + backend + frontend-build + webapp
```

## クイックスタート (Docker Compose)

```bash
docker compose up -d --build
```

起動後:
- Web / API (Express経由): http://localhost:3001
- FastAPI 直接 (OpenAPI: `/docs`): http://localhost:8001
- PostgreSQL: `localhost:5433` (コンテナ内部は5432)

初回起動時に `python -m app.seed` が自動実行され、サンプル会社
(`JP001`, `US001`) と組織を投入する。

**ホストポートについて**: このマシンには既に 5432/8000/3000 を使う別サービス
(ローカルPostgres、Docker Desktop、別の開発サーバー等) が存在していたため、
衝突を避けて 5433 / 8001 / 3001 をホスト側に割り当てている。競合がない環境
では `docker-compose.yml` のポート番号は自由に戻してよい。

## 認証 (開発用)

本番は企業SSO / OAuth2アクセストークンに置き換える想定 (spec 7.1, 10, 13:
実装前に確定する事項)。ローカル検証用に `POST /api/v1/auth/dev-token` で
同じ権限モデル (ロール・会社スコープ) を持つJWTを発行できる。フロントエンド
のログイン画面はこのエンドポイントを呼び出すフォームになっている。

ロール: `CENTRAL_ADMIN` (中央管理者) / `COMPANY_HR` (会社人事担当者) /
`VIEWER` (閲覧者) / `API_ACCOUNT` (API連携アカウント)。`companies` に
会社コードの配列 (全社は `["*"]`) を指定する。

```bash
curl -X POST http://localhost:8001/api/v1/auth/dev-token \
  -H "Content-Type: application/json" \
  -d '{"sub":"admin","display_name":"Admin","roles":["CENTRAL_ADMIN"],"companies":["*"]}'
```

## ローカル開発 (Dockerなし)

### バックエンド

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash. PowerShellは .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# PostgreSQLが無い場合は SQLite でも動作確認可能 (テストと同じ方式)
export DATABASE_URL="sqlite:///./dev.db"
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

### テスト

```bash
cd backend
source .venv/Scripts/activate
python -m pytest -q
```

Luhn(モジュラス10)チェックデジット計算、採番、照合・確認待ちフロー、
Idempotency-Key処理、JSONバルク登録、CSV一括登録のテストを含む
(全19件、SQLiteで実行)。

### フロントエンド

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173, /api は vite.config.js で backend:8000 にプロキシ
```

### Webアプリ層 (Express)

```bash
cd frontend && npm run build
cd ../webapp
npm install
FASTAPI_TARGET=http://localhost:8000 STATIC_DIR=../frontend/dist node server.js
```

## 実装状況

### 仕様書どおりに実装したコア機能

- **統一社員番号の採番・検証** (spec 4.1): `E`+7桁連番+Luhn(モジュラス10)
  チェックデジット。`MAX+1`ではなくカウンタ行への`UPDATE...RETURNING`で採番
  し、一意制約を二重の防御線とする。仕様書のチェックデジット計算例
  (`E00000018`, `E00000026`, `E12345674`) をテストで検証済み。
- **英語名称の正規化** (spec 3.1): NFKC正規化・トリム・空白単一化・大文字化
  のみ。原文は別カラムに保持し、姓名の並べ替えや削除は行わない。
- **照合・確認待ちフロー** (spec 4.2, 4.3): 会社+既存社員番号の対応検索→
  一致すれば既存番号を返却 (`EXISTING`)、矛盾があれば確認待ち。対応が
  無ければ英語名称+生年月日で候補検索→候補が無ければ新規採番
  (`CREATED`)、あれば確認待ち (`REVIEW_REQUIRED`)。確認待ちは
  `identity_reviews` に分離保存し、中央管理者が関連付け・別人採番・却下を
  選択できる。
- **同時実行対策**: 照合キー (正規化名+生年月日) 単位でDB行ロックし、
  照合から確定までを直列化 (PostgreSQLでは`SELECT...FOR UPDATE`)。
- **Idempotency-Key** (spec 7.1, 7.4.2): 同一呼出元・キー・内容の再送には
  保存済みレスポンスを返却、内容が異なれば`409`。
- **個別登録・検索・更新API** (spec 7.2, 7.3): 楽観ロック (`version`)、
  権限に応じた生年月日・備考のマスク、監査ログ記録。
- **CSV一括登録** (spec 6): アップロード→非同期事前検証 (件数見込みのみ、
  未採番)→実行 (行ごとに独立トランザクションで確定)→結果CSV/JSON取得。
  数式インジェクション対策済み。ジョブID+行番号の一意制約で再実行時の
  二重登録を防止。
- **JSONバルク登録** (spec 7.4): `/employee-batches`。個別登録・CSVと同じ
  共通登録サービスを使用。`client_record_id`の重複チェック、部分成功
  (行単位トランザクション)、キャンセル、状態・結果のページング取得。
- **権限モデル** (spec 10): 中央管理者・会社人事担当者・閲覧者・API連携
  アカウントの4ロール。会社単位のアクセス制御、生年月日・備考の閲覧制御。

### 意図的な簡略化・本番実装前に置き換えが必要な箇所

- **認証**: 企業SSO/OAuth2の代わりに開発用JWT発行エンドポイントを実装。
  本番では `app/security.py` の `get_current_user` を実際のトークン検証に
  差し替える (spec 13)。
- **非同期ワーカー**: 独立したジョブキュー (Celery/RQ等) の代わりに
  FastAPIの`BackgroundTasks` (スレッドプール実行) を使用。ジョブ状態は
  DBに永続化しているため置き換えは`workers/`層のみで完結する設計
  (spec 13)。
- **Webサーバー入口**: Apache/Nginxは未構成。Docker Composeでは
  Express (`webapp`) を直接公開している。本番導入時にリバースプロキシを
  追加する (spec 9.1, 13で選定未確定)。
- **DBマイグレーション**: Alembicの雛形 (`backend/alembic/`) のみ用意。
  実際のリビジョンファイルは、PostgreSQLに接続した状態で
  `alembic revision --autogenerate -m "initial"` を実行して生成すること。
  開発用に`app.main`起動時の`Base.metadata.create_all`でテーブルを自動作成
  している。
- **統合・エイリアス機能** (spec 4.3, `employee_number_aliases`テーブル):
  データモデルのみ用意し、統合実行APIは未実装 (中央管理者向けの重複統合
  フローは実装前に確定する事項が多いため)。
- **Excel対応、多言語UI、多要素認証、越境データ管理**: 仕様書が
  「暫定」「推奨」「実装前に確定」と明記している項目 (spec 13) は未実装。

## API概要

OpenAPI定義はFastAPI起動時に自動生成される (`/docs`, `/openapi.json`)。
主要エンドポイントは仕様書 7.2, 7.4.1 のとおり `/api/v1` 配下に実装済み。
