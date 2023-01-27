--
-- PostgreSQL database dump
--

-- Dumped from database version 12.12 (Ubuntu 12.12-0ubuntu0.20.04.1)
-- Dumped by pg_dump version 12.12 (Ubuntu 12.12-0ubuntu0.20.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner:
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: image; Type: TABLE; Schema: public; Owner: peter
--

CREATE TABLE public.image (
    id integer NOT NULL,
    image_path text,
    name character varying(200) NOT NULL,
    created_date timestamp with time zone DEFAULT now(),
    file_size bigint,
    hits integer,
    uploader integer,
    ratings integer
);


ALTER TABLE public.image OWNER TO peter;

--
-- Name: image_hits; Type: TABLE; Schema: public; Owner: peter
--

CREATE TABLE public.image_hits (
    hit_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    image_id integer,
    user_id integer,
    hit_date timestamp with time zone DEFAULT now()
);


ALTER TABLE public.image_hits OWNER TO peter;

--
-- Name: image_id_seq; Type: SEQUENCE; Schema: public; Owner: peter
--

CREATE SEQUENCE public.image_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.image_id_seq OWNER TO peter;

--
-- Name: image_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: peter
--

ALTER SEQUENCE public.image_id_seq OWNED BY public.image.id;


--
-- Name: tag; Type: TABLE; Schema: public; Owner: peter
--

CREATE TABLE public.tag (
    id integer NOT NULL,
    name character varying(100)
);


ALTER TABLE public.tag OWNER TO peter;

--
-- Name: tag_image; Type: TABLE; Schema: public; Owner: peter
--

CREATE TABLE public.tag_image (
    id integer NOT NULL,
    image integer,
    tag integer
);


ALTER TABLE public.tag_image OWNER TO peter;

--
-- Name: images_per_tag; Type: VIEW; Schema: public; Owner: peter
--

CREATE VIEW public.images_per_tag AS
 SELECT tag.name,
    count(*) AS images
   FROM (public.tag_image
     JOIN public.tag ON ((tag.id = tag_image.tag)))
  GROUP BY tag.name
  ORDER BY (count(*)) DESC;


ALTER TABLE public.images_per_tag OWNER TO peter;

--
-- Name: ratings; Type: TABLE; Schema: public; Owner: peter
--

CREATE TABLE public.ratings (
    id integer NOT NULL,
    "user" integer,
    image integer,
    rating integer,
    date timestamp with time zone DEFAULT now()
);


ALTER TABLE public.ratings OWNER TO peter;

--
-- Name: tagged_images; Type: VIEW; Schema: public; Owner: peter
--

CREATE VIEW public.tagged_images AS
 SELECT image.id,
    image.image_path,
    image.name,
    image.created_date,
    image.file_size,
    image.hits,
    image.uploader,
    image.ratings,
    ( SELECT json_agg(tag.name) AS json_agg
           FROM (public.tag_image
             JOIN public.tag ON ((tag_image.tag = tag.id)))
          WHERE (tag_image.image = image.id)) AS tags,
    ( SELECT avg(ratings.rating) AS avg
           FROM public.ratings
          WHERE (ratings.image = image.id)) AS rating,
    ( SELECT count(ratings.rating) AS count
           FROM public.ratings
          WHERE (ratings.image = image.id)) AS rating_count,
    ( SELECT max(ratings.rating) AS max
           FROM public.ratings
          WHERE (ratings.image = image.id)) AS rating_top,
    ( SELECT max(ratings.date) AS max
           FROM public.ratings
          WHERE (ratings.image = image.id)) AS rating_last_rated
   FROM public.image;


ALTER TABLE public.tagged_images OWNER TO peter;

--
-- Name: images_with_tag; Type: VIEW; Schema: public; Owner: peter
--

CREATE VIEW public.images_with_tag AS
 SELECT tag.name AS tag_name,
    tagged_images.id,
    tagged_images.image_path,
    tagged_images.name,
    tagged_images.created_date,
    tagged_images.file_size,
    tagged_images.hits,
    tagged_images.uploader,
    tagged_images.ratings,
    tagged_images.tags,
    tagged_images.rating,
    tagged_images.rating_count,
    tagged_images.rating_top,
    tagged_images.rating_last_rated
   FROM ((public.tag_image
     JOIN public.tag ON ((tag.id = tag_image.tag)))
     JOIN public.tagged_images ON ((tagged_images.id = tag_image.image)))
  WHERE (tag_image.tag IS NOT NULL);


ALTER TABLE public.images_with_tag OWNER TO peter;

--
-- Name: message; Type: TABLE; Schema: public; Owner: peter
--

CREATE TABLE public.message (
    id integer NOT NULL,
    from_user integer,
    image integer,
    text character varying(500),
    reply_to integer,
    message_date timestamp with time zone DEFAULT now()
);


ALTER TABLE public.message OWNER TO peter;

--
-- Name: message_id_seq; Type: SEQUENCE; Schema: public; Owner: peter
--

CREATE SEQUENCE public.message_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.message_id_seq OWNER TO peter;

--
-- Name: message_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: peter
--

ALTER SEQUENCE public.message_id_seq OWNED BY public.message.id;


--
-- Name: most_visited_tags; Type: VIEW; Schema: public; Owner: peter
--

CREATE VIEW public.most_visited_tags AS
 SELECT
 tag.name AS tag,
    count(*) AS visits,
    max(image_hits.hit_date) AS last_visited,
    (select image_path from image where image.id = min(tag_image.image)) as most_viewed_image_path,
    (select id from image where image.id = min(tag_image.image)) as most_viewed_image_id
   FROM (((public.image
     JOIN public.image_hits ON ((image_hits.image_id = image.id)))
     JOIN public.tag_image ON ((tag_image.image = image.id)))
     JOIN public.tag ON ((tag.id = tag_image.tag)))
  WHERE (image_hits.hit_date > (CURRENT_DATE - '30 days'::interval day))
  GROUP BY tag.name
  ORDER BY (count(*)) DESC;


ALTER TABLE public.most_visited_tags OWNER TO peter;

--
-- Name: ratings_id_seq; Type: SEQUENCE; Schema: public; Owner: peter
--

CREATE SEQUENCE public.ratings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.ratings_id_seq OWNER TO peter;

--
-- Name: ratings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: peter
--

ALTER SEQUENCE public.ratings_id_seq OWNED BY public.ratings.id;


--
-- Name: tag_id_seq; Type: SEQUENCE; Schema: public; Owner: peter
--

CREATE SEQUENCE public.tag_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.tag_id_seq OWNER TO peter;

--
-- Name: tag_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: peter
--

ALTER SEQUENCE public.tag_id_seq OWNED BY public.tag.id;


--
-- Name: tag_image_id_seq; Type: SEQUENCE; Schema: public; Owner: peter
--

CREATE SEQUENCE public.tag_image_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.tag_image_id_seq OWNER TO peter;

--
-- Name: tag_image_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: peter
--

ALTER SEQUENCE public.tag_image_id_seq OWNED BY public.tag_image.id;


--
-- Name: tag_with_last_imageid; Type: VIEW; Schema: public; Owner: peter
--

CREATE VIEW public.tag_with_last_imageid AS
 SELECT tag.name,
    count(*) AS images,
    max(tag_image.image) AS max
   FROM ((public.tag_image
     JOIN public.tag ON ((tag.id = tag_image.tag)))
     JOIN public.image ON ((image.id = tag_image.image)))
  GROUP BY tag.name
  ORDER BY (count(*)) DESC;


ALTER TABLE public.tag_with_last_imageid OWNER TO peter;

--
-- Name: user; Type: TABLE; Schema: public; Owner: peter
--

CREATE TABLE public."user" (
    id integer NOT NULL,
    name character varying(100),
    registered timestamp with time zone,
    karma integer,
    privileges character varying(100),
    banned boolean,
    password character varying(256)
);


ALTER TABLE public."user" OWNER TO peter;

--
-- Name: user_id_seq; Type: SEQUENCE; Schema: public; Owner: peter
--

CREATE SEQUENCE public.user_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.user_id_seq OWNER TO peter;

--
-- Name: user_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: peter
--

ALTER SEQUENCE public.user_id_seq OWNED BY public."user".id;


--
-- Name: image id; Type: DEFAULT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.image ALTER COLUMN id SET DEFAULT nextval('public.image_id_seq'::regclass);


--
-- Name: message id; Type: DEFAULT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.message ALTER COLUMN id SET DEFAULT nextval('public.message_id_seq'::regclass);


--
-- Name: ratings id; Type: DEFAULT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.ratings ALTER COLUMN id SET DEFAULT nextval('public.ratings_id_seq'::regclass);


--
-- Name: tag id; Type: DEFAULT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.tag ALTER COLUMN id SET DEFAULT nextval('public.tag_id_seq'::regclass);


--
-- Name: tag_image id; Type: DEFAULT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.tag_image ALTER COLUMN id SET DEFAULT nextval('public.tag_image_id_seq'::regclass);


--
-- Name: user id; Type: DEFAULT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public."user" ALTER COLUMN id SET DEFAULT nextval('public.user_id_seq'::regclass);


--
-- Name: image_hits image_hits_pkey; Type: CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.image_hits
    ADD CONSTRAINT image_hits_pkey PRIMARY KEY (hit_id);


--
-- Name: image image_image_path_key; Type: CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.image
    ADD CONSTRAINT image_image_path_key UNIQUE (image_path);


--
-- Name: image image_pkey; Type: CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.image
    ADD CONSTRAINT image_pkey PRIMARY KEY (id);


--
-- Name: message message_pkey; Type: CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.message
    ADD CONSTRAINT message_pkey PRIMARY KEY (id);


--
-- Name: tag name_is_unique; Type: CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.tag
    ADD CONSTRAINT name_is_unique UNIQUE (name);


--
-- Name: ratings ratings_pkey; Type: CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.ratings
    ADD CONSTRAINT ratings_pkey PRIMARY KEY (id);


--
-- Name: tag_image tag_image_pkey; Type: CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.tag_image
    ADD CONSTRAINT tag_image_pkey PRIMARY KEY (id);


--
-- Name: tag tag_pkey; Type: CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.tag
    ADD CONSTRAINT tag_pkey PRIMARY KEY (id);


--
-- Name: tag_image unique_component_commit; Type: CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.tag_image
    ADD CONSTRAINT unique_component_commit UNIQUE (tag, image);


--
-- Name: user user_pkey; Type: CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public."user"
    ADD CONSTRAINT user_pkey PRIMARY KEY (id);


--
-- Name: image_image_path_idx; Type: INDEX; Schema: public; Owner: peter
--

CREATE INDEX image_image_path_idx ON public.image USING btree (image_path);


--
-- Name: image_name_idx; Type: INDEX; Schema: public; Owner: peter
--

CREATE INDEX image_name_idx ON public.image USING btree (name);


--
-- Name: tag_image_image_idx; Type: INDEX; Schema: public; Owner: peter
--

CREATE INDEX tag_image_image_idx ON public.tag_image USING hash (image);


--
-- Name: image_hits image_hits_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.image_hits
    ADD CONSTRAINT image_hits_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(id);


--
-- Name: image image_ratings_fkey; Type: FK CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.image
    ADD CONSTRAINT image_ratings_fkey FOREIGN KEY (ratings) REFERENCES public.ratings(id);


--
-- Name: image image_uploader_fkey; Type: FK CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.image
    ADD CONSTRAINT image_uploader_fkey FOREIGN KEY (uploader) REFERENCES public."user"(id);


--
-- Name: message message_from_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.message
    ADD CONSTRAINT message_from_user_fkey FOREIGN KEY (from_user) REFERENCES public."user"(id);


--
-- Name: message message_image_fkey; Type: FK CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.message
    ADD CONSTRAINT message_image_fkey FOREIGN KEY (image) REFERENCES public.image(id);


--
-- Name: message message_reply_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.message
    ADD CONSTRAINT message_reply_to_fkey FOREIGN KEY (reply_to) REFERENCES public.message(id);


--
-- Name: ratings ratings_image_fkey; Type: FK CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.ratings
    ADD CONSTRAINT ratings_image_fkey FOREIGN KEY (image) REFERENCES public.image(id);


--
-- Name: ratings ratings_user_fkey; Type: FK CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.ratings
    ADD CONSTRAINT ratings_user_fkey FOREIGN KEY ("user") REFERENCES public."user"(id);


--
-- Name: tag_image tag_image_image_fkey; Type: FK CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.tag_image
    ADD CONSTRAINT tag_image_image_fkey FOREIGN KEY (image) REFERENCES public.image(id);


--
-- Name: tag_image tag_image_tag_fkey; Type: FK CONSTRAINT; Schema: public; Owner: peter
--

ALTER TABLE ONLY public.tag_image
    ADD CONSTRAINT tag_image_tag_fkey FOREIGN KEY (tag) REFERENCES public.tag(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

