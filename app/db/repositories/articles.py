import json
from typing import List, Optional, Sequence, Tuple, Union

from asyncpg import Connection, Record
from pypika import Query

from app.db.errors import EntityDoesNotExist
from app.db.queries.queries import queries
from app.db.queries.tables import (
    Parameter,
    articles,
    articles_to_tags,
    favorites,
    tags as tags_table,
    users,
)
from app.db.repositories.base import BaseRepository
from app.db.repositories.profiles import ProfilesRepository
from app.db.repositories.tags import TagsRepository
from app.models.domain.articles import Article
from app.models.domain.profiles import Profile
from app.models.domain.users import User
from app.models.schemas.articles import ArticleAIAnalysis

AUTHOR_USERNAME_ALIAS = "author_username"
SLUG_ALIAS = "slug"

CAMEL_OR_SNAKE_CASE_TO_WORDS = r"^[a-z\d_\-]+|[A-Z\d_\-][^A-Z\d_\-]*"


class ArticlesRepository(BaseRepository):  # noqa: WPS214
    def __init__(self, conn: Connection) -> None:
        super().__init__(conn)
        self._profiles_repo = ProfilesRepository(conn)
        self._tags_repo = TagsRepository(conn)

    async def create_article(  # noqa: WPS211
        self,
        *,
        slug: str,
        title: str,
        description: str,
        body: str,
        author: User,
        tags: Optional[Sequence[str]] = None,
        content_status: str = "visible",
    ) -> Article:
        async with self.connection.transaction():
            article_row = await queries.create_new_article(
                self.connection,
                slug=slug,
                title=title,
                description=description,
                body=body,
                author_username=author.username,
                content_status=content_status,
            )

            if tags:
                await self._tags_repo.create_tags_that_dont_exist(tags=tags)
                await self._link_article_with_tags(slug=slug, tags=tags)

        return await self._get_article_from_db_record(
            article_row=article_row,
            slug=slug,
            author_username=article_row[AUTHOR_USERNAME_ALIAS],
            requested_user=author,
        )

    async def update_article(  # noqa: WPS211
        self,
        *,
        article: Article,
        slug: Optional[str] = None,
        title: Optional[str] = None,
        body: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
    ) -> Article:
        updated_article = article.copy(deep=True)
        updated_article.slug = slug or updated_article.slug
        updated_article.title = title or article.title
        updated_article.body = body or article.body
        updated_article.description = description or article.description
        updated_article.tags = list(tags) if tags is not None else article.tags

        async with self.connection.transaction():
            updated_article.updated_at = await queries.update_article(
                self.connection,
                slug=article.slug,
                author_username=article.author.username,
                new_slug=updated_article.slug,
                new_title=updated_article.title,
                new_body=updated_article.body,
                new_description=updated_article.description,
            )
            if tags is not None:
                await self.connection.execute(
                    """
                    DELETE FROM articles_to_tags
                    WHERE article_id = (
                        SELECT id
                        FROM articles
                        WHERE slug = $1
                    )
                    """,
                    updated_article.slug,
                )
                if tags:
                    await self._tags_repo.create_tags_that_dont_exist(tags=tags)
                    await self._link_article_with_tags(
                        slug=updated_article.slug,
                        tags=tags,
                    )

        return updated_article

    async def delete_article(self, *, article: Article) -> None:
        async with self.connection.transaction():
            await queries.delete_article(
                self.connection,
                slug=article.slug,
                author_username=article.author.username,
            )

    async def filter_articles(  # noqa: WPS211
        self,
        *,
        tag: Optional[str] = None,
        q: Optional[str] = None,
        author: Optional[str] = None,
        favorited: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        requested_user: Optional[User] = None,
    ) -> List[Article]:
        query_params: List[Union[str, int]] = []
        query_params_count = 0

        # fmt: off
        query = Query.from_(
            articles,
        ).select(
            articles.id,
            articles.slug,
            articles.title,
            articles.description,
            articles.body,
            articles.content_status,
            articles.created_at,
            articles.updated_at,
            Query.from_(
                users,
            ).where(
                users.id == articles.author_id,
            ).select(
                users.username,
            ).as_(
                AUTHOR_USERNAME_ALIAS,
            ),
        ).where(
            articles.content_status == "visible",
        )
        # fmt: on

        if tag:
            query_params.append(tag)
            query_params_count += 1

            # fmt: off
            query = query.join(
                articles_to_tags,
            ).on(
                (articles.id == articles_to_tags.article_id) & (
                    articles_to_tags.tag == Query.from_(
                        tags_table,
                    ).where(
                        tags_table.tag == Parameter(query_params_count),
                    ).select(
                        tags_table.tag,
                    )
                ),
            )
            # fmt: on

        if q:
            query_params.append("%{0}%".format(q))
            query_params_count += 1
            search_parameter = Parameter(query_params_count)

            query = query.where(
                articles.title.ilike(search_parameter)
                | articles.description.ilike(search_parameter)
                | articles.body.ilike(search_parameter)
                | articles.id.isin(
                    Query.from_(
                        articles_to_tags,
                    ).where(
                        articles_to_tags.tag.ilike(search_parameter),
                    ).select(
                        articles_to_tags.article_id,
                    ),
                ),
            )

        if author:
            query_params.append(author)
            query_params_count += 1

            # fmt: off
            query = query.join(
                users,
            ).on(
                (articles.author_id == users.id) & (
                    users.id == Query.from_(
                        users,
                    ).where(
                        users.username == Parameter(query_params_count),
                    ).select(
                        users.id,
                    )
                ),
            )
            # fmt: on

        if favorited:
            query_params.append(favorited)
            query_params_count += 1

            # fmt: off
            query = query.join(
                favorites,
            ).on(
                (articles.id == favorites.article_id) & (
                    favorites.user_id == Query.from_(
                        users,
                    ).where(
                        users.username == Parameter(query_params_count),
                    ).select(
                        users.id,
                    )
                ),
            )
            # fmt: on

        query = query.limit(Parameter(query_params_count + 1)).offset(
            Parameter(query_params_count + 2),
        )
        query_params.extend([limit, offset])

        articles_rows = await self.connection.fetch(query.get_sql(), *query_params)

        return [
            await self._get_article_from_db_record(
                article_row=article_row,
                slug=article_row[SLUG_ALIAS],
                author_username=article_row[AUTHOR_USERNAME_ALIAS],
                requested_user=requested_user,
            )
            for article_row in articles_rows
        ]

    async def get_articles_for_user_feed(
        self,
        *,
        user: User,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Article]:
        articles_rows = await queries.get_articles_for_feed(
            self.connection,
            follower_username=user.username,
            limit=limit,
            offset=offset,
        )
        return [
            await self._get_article_from_db_record(
                article_row=article_row,
                slug=article_row[SLUG_ALIAS],
                author_username=article_row[AUTHOR_USERNAME_ALIAS],
                requested_user=user,
            )
            for article_row in articles_rows
        ]

    async def get_article_by_slug(
        self,
        *,
        slug: str,
        requested_user: Optional[User] = None,
    ) -> Article:
        article_row = await queries.get_article_by_slug(self.connection, slug=slug)
        if article_row:
            return await self._get_article_from_db_record(
                article_row=article_row,
                slug=article_row[SLUG_ALIAS],
                author_username=article_row[AUTHOR_USERNAME_ALIAS],
                requested_user=requested_user,
            )

        raise EntityDoesNotExist("article with slug {0} does not exist".format(slug))

    async def get_article_by_slug_any_status(
        self,
        *,
        slug: str,
        requested_user: Optional[User] = None,
    ) -> Article:
        article_row = await self.connection.fetchrow(
            """
            SELECT id,
                   slug,
                   title,
                   description,
                   body,
                   content_status,
                   created_at,
                   updated_at,
                   (SELECT username FROM users WHERE id = author_id) AS author_username
            FROM articles
            WHERE slug = $1
            LIMIT 1
            """,
            slug,
        )
        if article_row:
            return await self._get_article_from_db_record(
                article_row=article_row,
                slug=article_row[SLUG_ALIAS],
                author_username=article_row[AUTHOR_USERNAME_ALIAS],
                requested_user=requested_user,
            )
        raise EntityDoesNotExist("article with slug {0} does not exist".format(slug))

    async def get_tags_for_article_by_slug(self, *, slug: str) -> List[str]:
        tag_rows = await queries.get_tags_for_article_by_slug(
            self.connection,
            slug=slug,
        )
        return [row["tag"] for row in tag_rows]

    async def get_favorites_count_for_article_by_slug(self, *, slug: str) -> int:
        return (
            await queries.get_favorites_count_for_article(self.connection, slug=slug)
        )["favorites_count"]

    async def is_article_favorited_by_user(self, *, slug: str, user: User) -> bool:
        return (
            await queries.is_article_in_favorites(
                self.connection,
                username=user.username,
                slug=slug,
            )
        )["favorited"]

    async def add_article_into_favorites(self, *, article: Article, user: User) -> None:
        await queries.add_article_to_favorites(
            self.connection,
            username=user.username,
            slug=article.slug,
        )

    async def remove_article_from_favorites(
        self,
        *,
        article: Article,
        user: User,
    ) -> None:
        await queries.remove_article_from_favorites(
            self.connection,
            username=user.username,
            slug=article.slug,
        )

    async def is_article_embedding_fresh(
        self,
        *,
        article: Article,
        model_name: str,
        content_hash: str,
    ) -> bool:
        row = await self.connection.fetchrow(
            """
            SELECT TRUE AS fresh
            FROM article_embeddings
            WHERE article_id = $1
              AND model_name = $2
              AND content_hash = $3
            """,
            article.id_,
            model_name,
            content_hash,
        )
        return bool(row)

    async def upsert_article_embedding(
        self,
        *,
        article: Article,
        model_name: str,
        content_hash: str,
        embedding: Sequence[float],
    ) -> None:
        await self.connection.execute(
            """
            INSERT INTO article_embeddings (
                article_id,
                model_name,
                content_hash,
                embedding
            )
            VALUES ($1, $2, $3, $4::vector)
            ON CONFLICT (article_id)
            DO UPDATE SET
                model_name = EXCLUDED.model_name,
                content_hash = EXCLUDED.content_hash,
                embedding = EXCLUDED.embedding,
                updated_at = now()
            """,
            article.id_,
            model_name,
            content_hash,
            self._format_embedding(embedding),
        )

    async def get_recommended_articles(
        self,
        *,
        slug: str,
        limit: int,
        requested_user: Optional[User],
    ) -> List[Tuple[Article, float]]:
        article_rows = await self.connection.fetch(
            """
            SELECT
                a.id,
                a.slug,
                a.title,
                a.description,
                a.body,
                a.content_status,
                a.created_at,
                a.updated_at,
                (SELECT username FROM users WHERE id = a.author_id) AS author_username,
                1 - (source.embedding <=> target.embedding) AS similarity_score
            FROM article_embeddings source
            INNER JOIN article_embeddings target
                ON target.article_id != source.article_id
            INNER JOIN articles source_article
                ON source_article.id = source.article_id
            INNER JOIN articles a
                ON a.id = target.article_id
            WHERE source_article.slug = $1
              AND source_article.content_status = 'visible'
              AND a.content_status = 'visible'
            ORDER BY source.embedding <=> target.embedding
            LIMIT $2
            """,
            slug,
            limit,
        )
        return [
            (
                await self._get_article_from_db_record(
                    article_row=article_row,
                    slug=article_row[SLUG_ALIAS],
                    author_username=article_row[AUTHOR_USERNAME_ALIAS],
                    requested_user=requested_user,
                ),
                float(article_row["similarity_score"]),
            )
            for article_row in article_rows
        ]

    async def search_articles_by_embedding(
        self,
        *,
        embedding: Sequence[float],
        limit: int,
        requested_user: Optional[User],
    ) -> List[Tuple[Article, float]]:
        article_rows = await self.connection.fetch(
            """
            SELECT
                a.id,
                a.slug,
                a.title,
                a.description,
                a.body,
                a.content_status,
                a.created_at,
                a.updated_at,
                (SELECT username FROM users WHERE id = a.author_id) AS author_username,
                1 - (e.embedding <=> $1::vector) AS similarity_score
            FROM article_embeddings e
            INNER JOIN articles a
                ON a.id = e.article_id
            WHERE a.content_status = 'visible'
            ORDER BY e.embedding <=> $1::vector
            LIMIT $2
            """,
            self._format_embedding(embedding),
            limit,
        )
        return [
            (
                await self._get_article_from_db_record(
                    article_row=article_row,
                    slug=article_row[SLUG_ALIAS],
                    author_username=article_row[AUTHOR_USERNAME_ALIAS],
                    requested_user=requested_user,
                ),
                float(article_row["similarity_score"]),
            )
            for article_row in article_rows
        ]

    def _format_embedding(self, embedding: Sequence[float]) -> str:
        return "[{0}]".format(",".join(str(value) for value in embedding))

    async def create_moderation_log(
        self,
        *,
        article: Article,
        analysis: ArticleAIAnalysis,
        allowed: bool,
        review_status: str,
    ) -> None:
        await self.connection.execute(
            """
            INSERT INTO article_moderation_logs (
                article_id,
                author_id,
                allowed,
                content_score,
                risk_labels,
                summary,
                suggestions,
                model_name,
                raw_response,
                review_status
            )
            VALUES (
                $1,
                (SELECT id FROM users WHERE username = $2),
                $3,
                $4,
                $5::json,
                $6,
                $7::json,
                $8,
                $9::json,
                $10
            )
            """,
            article.id_,
            article.author.username,
            allowed,
            analysis.content_score,
            json.dumps(analysis.risk_labels),
            analysis.summary,
            json.dumps(analysis.suggestions),
            analysis.model,
            analysis.json(by_alias=True),
            review_status,
        )

    async def set_article_content_status(self, *, slug: str, status: str) -> None:
        result = await self.connection.execute(
            """
            UPDATE articles
            SET content_status = $2
            WHERE slug = $1
            """,
            slug,
            status,
        )
        if result == "UPDATE 0":
            raise EntityDoesNotExist(
                "article with slug {0} does not exist".format(slug),
            )

    async def _get_article_from_db_record(
        self,
        *,
        article_row: Record,
        slug: str,
        author_username: str,
        requested_user: Optional[User],
    ) -> Article:
        if author_username:
            author = await self._profiles_repo.get_profile_by_username(
                username=author_username,
                requested_user=requested_user,
            )
        else:
            author = Profile(
                username="已删除用户",
                bio="",
                image=None,
                following=False,
            )
        return Article(
            id_=article_row["id"],
            slug=slug,
            title=article_row["title"],
            description=article_row["description"],
            body=article_row["body"],
            content_status=article_row["content_status"],
            author=author,
            tags=await self.get_tags_for_article_by_slug(slug=slug),
            favorites_count=await self.get_favorites_count_for_article_by_slug(
                slug=slug,
            ),
            favorited=await self.is_article_favorited_by_user(
                slug=slug,
                user=requested_user,
            )
            if requested_user
            else False,
            created_at=article_row["created_at"],
            updated_at=article_row["updated_at"],
        )

    async def get_recommendation_reason_cache(
        self,
        *,
        source_article_id: int,
        target_article_id: int,
        model_name: str,
    ) -> Optional[Tuple[float, str]]:
        row = await self.connection.fetchrow(
            """
            SELECT relevance_score, reason
            FROM recommendation_reason_cache
            WHERE source_article_id = $1
              AND target_article_id = $2
              AND model_name = $3
            """,
            source_article_id,
            target_article_id,
            model_name,
        )
        if row:
            return float(row["relevance_score"]), row["reason"]
        return None

    async def upsert_recommendation_reason_cache(
        self,
        *,
        source_article_id: int,
        target_article_id: int,
        model_name: str,
        relevance_score: float,
        reason: str,
    ) -> None:
        await self.connection.execute(
            """
            INSERT INTO recommendation_reason_cache
                (source_article_id, target_article_id, model_name, relevance_score, reason)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT ON CONSTRAINT uq_recommendation_reason_cache
            DO UPDATE SET
                relevance_score = EXCLUDED.relevance_score,
                reason = EXCLUDED.reason,
                created_at = now()
            """,
            source_article_id,
            target_article_id,
            model_name,
            relevance_score,
            reason,
        )

    async def _link_article_with_tags(self, *, slug: str, tags: Sequence[str]) -> None:
        await queries.add_tags_to_article(
            self.connection,
            [{SLUG_ALIAS: slug, "tag": tag} for tag in tags],
        )
