--
-- PostgreSQL database dump
--

\restrict fidGOcFysbnLvs7rLB3Cf2N8w54bMYbzvNZ2tjHugdcE5Hd00FCvAO9fzPjjWLf

-- Dumped from database version 16.11 (Debian 16.11-1.pgdg12+1)
-- Dumped by pg_dump version 16.11 (Debian 16.11-1.pgdg12+1)

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
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: event_severity_enum; Type: TYPE; Schema: public; Owner: user
--

CREATE TYPE public.event_severity_enum AS ENUM (
    'CRITICAL',
    'HIGH',
    'MEDIUM',
    'LOW',
    'INFO'
);


ALTER TYPE public.event_severity_enum OWNER TO "user";

--
-- Name: event_status_enum; Type: TYPE; Schema: public; Owner: user
--

CREATE TYPE public.event_status_enum AS ENUM (
    'PENDING',
    'ACKNOWLEDGED',
    'RESOLVED',
    'FALSE_POSITIVE'
);


ALTER TYPE public.event_status_enum OWNER TO "user";

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: user
--

CREATE TABLE public.audit_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    module character varying(50),
    action character varying(50),
    target_id uuid,
    details jsonb,
    ip_address inet,
    user_agent text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.audit_logs OWNER TO "user";

--
-- Name: camera_ai_configs; Type: TABLE; Schema: public; Owner: user
--

CREATE TABLE public.camera_ai_configs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    camera_id uuid NOT NULL,
    event_type character varying(50) NOT NULL,
    default_severity public.event_severity_enum DEFAULT 'MEDIUM'::public.event_severity_enum NOT NULL,
    confidence_threshold numeric(4,3) DEFAULT 0.700 NOT NULL,
    debounce_seconds integer DEFAULT 60 NOT NULL,
    roi_polygon jsonb,
    active_schedule jsonb,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.camera_ai_configs OWNER TO "user";

--
-- Name: cameras; Type: TABLE; Schema: public; Owner: user
--

CREATE TABLE public.cameras (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(100) NOT NULL,
    rtsp_url text NOT NULL,
    location_name character varying(100),
    meta_info jsonb DEFAULT '{}'::jsonb,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.cameras OWNER TO "user";

--
-- Name: event_actions; Type: TABLE; Schema: public; Owner: user
--

CREATE TABLE public.event_actions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    event_id uuid NOT NULL,
    user_id uuid,
    previous_status public.event_status_enum,
    new_status public.event_status_enum,
    comment text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.event_actions OWNER TO "user";

--
-- Name: events; Type: TABLE; Schema: public; Owner: user
--

CREATE TABLE public.events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    camera_id uuid,
    config_id uuid,
    event_type character varying(50) NOT NULL,
    track_id character varying(100),
    confidence numeric(4,3),
    snapshot_path text,
    video_clip_path text,
    bbox jsonb,
    severity public.event_severity_enum DEFAULT 'MEDIUM'::public.event_severity_enum NOT NULL,
    status public.event_status_enum DEFAULT 'PENDING'::public.event_status_enum NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.events OWNER TO "user";

--
-- Name: faces; Type: TABLE; Schema: public; Owner: user
--

CREATE TABLE public.faces (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.faces OWNER TO "user";

--
-- Name: faces_id_seq; Type: SEQUENCE; Schema: public; Owner: user
--

CREATE SEQUENCE public.faces_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.faces_id_seq OWNER TO "user";

--
-- Name: faces_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: user
--

ALTER SEQUENCE public.faces_id_seq OWNED BY public.faces.id;


--
-- Name: permissions; Type: TABLE; Schema: public; Owner: user
--

CREATE TABLE public.permissions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    slug character varying(100) NOT NULL,
    description text
);


ALTER TABLE public.permissions OWNER TO "user";

--
-- Name: role_permissions; Type: TABLE; Schema: public; Owner: user
--

CREATE TABLE public.role_permissions (
    role_id uuid NOT NULL,
    permission_id uuid NOT NULL
);


ALTER TABLE public.role_permissions OWNER TO "user";

--
-- Name: roles; Type: TABLE; Schema: public; Owner: user
--

CREATE TABLE public.roles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    code character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    is_system_role boolean DEFAULT false NOT NULL
);


ALTER TABLE public.roles OWNER TO "user";

--
-- Name: users; Type: TABLE; Schema: public; Owner: user
--

CREATE TABLE public.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    username character varying(50) NOT NULL,
    email character varying(100) NOT NULL,
    password_hash character varying(255) NOT NULL,
    role_id uuid,
    full_name character varying(150),
    is_active boolean DEFAULT true NOT NULL,
    last_login timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.users OWNER TO "user";

--
-- Name: faces id; Type: DEFAULT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.faces ALTER COLUMN id SET DEFAULT nextval('public.faces_id_seq'::regclass);


--
-- Data for Name: audit_logs; Type: TABLE DATA; Schema: public; Owner: user
--

COPY public.audit_logs (id, user_id, module, action, target_id, details, ip_address, user_agent, created_at) FROM stdin;
\.


--
-- Data for Name: camera_ai_configs; Type: TABLE DATA; Schema: public; Owner: user
--

COPY public.camera_ai_configs (id, camera_id, event_type, default_severity, confidence_threshold, debounce_seconds, roi_polygon, active_schedule, is_active, created_at) FROM stdin;
\.


--
-- Data for Name: cameras; Type: TABLE DATA; Schema: public; Owner: user
--

COPY public.cameras (id, name, rtsp_url, location_name, meta_info, is_active, created_at, updated_at) FROM stdin;
1440355a-412f-41fe-a430-8f6b0390f27b	cam_701	rtsp://placeholder	\N	{}	t	2025-12-19 14:48:28.847213+00	2025-12-19 14:48:28.847213+00
cc9a1778-56aa-4bad-9b68-7a8ec5b5c316	cam_2201	rtsp://placeholder	\N	{}	t	2025-12-19 14:57:01.600555+00	2025-12-19 14:57:01.600555+00
\.


--
-- Data for Name: event_actions; Type: TABLE DATA; Schema: public; Owner: user
--

COPY public.event_actions (id, event_id, user_id, previous_status, new_status, comment, created_at) FROM stdin;
\.


--
-- Data for Name: events; Type: TABLE DATA; Schema: public; Owner: user
--

COPY public.events (id, camera_id, config_id, event_type, track_id, confidence, snapshot_path, video_clip_path, bbox, severity, status, created_at, occurred_at) FROM stdin;
0a607149-8dba-454c-91e7-4656933ad764	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	5	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:48:28.849808+00	2025-12-19 14:48:28.849808+00
b019cc57-bc95-40b4-8f04-0d05bda9ae9b	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	34	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:50:05.923713+00	2025-12-19 14:50:05.923713+00
db9a5402-e60c-4a92-8fa7-6a61c8e4c81e	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	74	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:52:25.225948+00	2025-12-19 14:52:25.225948+00
eb7abb22-a341-4a3b-957b-87523af874f3	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	133	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:54:26.489612+00	2025-12-19 14:54:26.489612+00
00bd669a-5dc1-4be3-b932-8b7616c6f7fd	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	136	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:54:27.89312+00	2025-12-19 14:54:27.89312+00
ee40411f-e9df-4ebb-92db-a7d35e1b179d	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	142	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:54:29.656642+00	2025-12-19 14:54:29.656642+00
4c6142e8-1de9-4a7d-8601-95c6381538a5	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	144	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:54:31.339447+00	2025-12-19 14:54:31.339447+00
a8be58e2-8b8a-496d-b753-e68e87eaa7c5	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	150	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:54:45.645386+00	2025-12-19 14:54:45.645386+00
4e0f436b-5f97-4d29-821f-07e95c623c5c	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	151	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:54:47.739911+00	2025-12-19 14:54:47.739911+00
144346e9-4e93-4139-bbb9-3ac7efe602c8	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	161	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:55:16.134596+00	2025-12-19 14:55:16.134596+00
bd057965-fae5-4da9-89ba-aa106a636718	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	174	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:55:29.341195+00	2025-12-19 14:55:29.341195+00
101d1e03-b1ea-47f6-ac2e-2ba9ce17d337	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	190	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:55:45.788501+00	2025-12-19 14:55:45.788501+00
8e595208-8695-476b-b3ec-510931f71595	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	221	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:56:29.052955+00	2025-12-19 14:56:29.052955+00
4da2a9c6-b7a0-4dcf-98b3-9ce1b6c4bd18	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	244	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:56:57.795805+00	2025-12-19 14:56:57.795805+00
2c22de39-370e-4808-a3cc-2c5ea43c09c6	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	294	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:58:19.707382+00	2025-12-19 14:58:19.707382+00
7e7512dd-334d-408a-8cdf-dab4889a036c	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	297	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:58:21.47131+00	2025-12-19 14:58:21.47131+00
2b9b9664-5133-4197-94a3-cd4602304447	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	306	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:58:51.178913+00	2025-12-19 14:58:51.178913+00
cbe1471f-784c-4985-98fd-6660471ff049	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	297	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:58:53.886507+00	2025-12-19 14:58:53.886507+00
9240762c-86fb-429a-9128-573c015cd6db	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	322	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:59:09.043099+00	2025-12-19 14:59:09.043099+00
4b132117-6970-43f9-915f-83c731e7c9fa	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	324	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 14:59:13.122714+00	2025-12-19 14:59:13.122714+00
9bd15fef-4fa2-4f97-9747-37a85c3b0a31	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	380	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:01:41.416526+00	2025-12-19 15:01:41.416526+00
2fa4ca7f-c256-457b-a109-a100f93b81a3	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	385	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:02:10.053747+00	2025-12-19 15:02:10.053747+00
976cb29a-debd-465f-9751-759054630cae	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	434	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:04:25.614821+00	2025-12-19 15:04:25.614821+00
9ba2715a-22a9-46db-8df2-e0bf0e494b03	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	458	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:07:26.252312+00	2025-12-19 15:07:26.252312+00
8d4ca0bb-9858-4345-b425-7a23aaaf428c	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	470	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:09:32.514754+00	2025-12-19 15:09:32.514754+00
e93c008c-7ed4-4bae-89ef-2f428727bc14	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	482	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:10:19.001572+00	2025-12-19 15:10:19.001572+00
0397fa0f-06b3-4100-a648-31c85213108d	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	483	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:10:21.368283+00	2025-12-19 15:10:21.368283+00
199644d1-4c08-488e-9212-a41fbbd16d4d	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	502	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:12:34.428153+00	2025-12-19 15:12:34.428153+00
3c544d46-8e63-4c78-88ba-1970c6d321df	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	603	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:21:25.503127+00	2025-12-19 15:21:25.503127+00
e13e5e84-5325-42fb-b0c2-5df16533e79c	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	599	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:21:37.923505+00	2025-12-19 15:21:37.923505+00
fd8eccd6-2e63-4cc5-a28d-b5ab5cfb36c1	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	608	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:21:41.009558+00	2025-12-19 15:21:41.009558+00
56fff457-c8a4-451a-9287-b0029b22b49f	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	608	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:22:18.019917+00	2025-12-19 15:22:18.019917+00
4291db09-512e-46de-bba0-09cee420b438	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	627	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:22:21.010554+00	2025-12-19 15:22:21.010554+00
1dd3f629-c670-4015-9a2f-2f09c22a0637	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	608	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:22:32.558895+00	2025-12-19 15:22:32.558895+00
b5e7d045-b82d-4dec-934e-56255866fdd8	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	640	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:22:42.612115+00	2025-12-19 15:22:42.612115+00
8beec177-c13e-4614-9520-da2e26293647	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	671	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:23:39.766359+00	2025-12-19 15:23:39.766359+00
7b552d8d-6476-45c9-9add-f44488684d62	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	671	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:24:06.814921+00	2025-12-19 15:24:06.814921+00
bdf6be40-8acb-4b38-a781-7469bec80160	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	708	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:24:09.034604+00	2025-12-19 15:24:09.034604+00
6f489a16-9d6a-4400-802b-c2e4da479012	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	710	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:24:09.035901+00	2025-12-19 15:24:09.035901+00
721ad448-45e2-4afc-803c-c5950b1bc35e	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	754	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:25:42.833744+00	2025-12-19 15:25:42.833744+00
01dba567-cd07-4311-825e-0b453f911814	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	774	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:26:09.829779+00	2025-12-19 15:26:09.829779+00
26a033df-9c50-4293-ba1d-180b52f3a5a1	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	774	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:26:26.881836+00	2025-12-19 15:26:26.881836+00
f4e74849-afd6-41ca-8b11-ead8e5133aa1	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	830	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:27:37.105509+00	2025-12-19 15:27:37.105509+00
ade2ca17-696a-46d0-91a7-4630b2bbce77	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	852	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:28:43.639951+00	2025-12-19 15:28:43.639951+00
492e7075-edb8-46a1-a34a-4bb1e8769688	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	862	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:29:27.376756+00	2025-12-19 15:29:27.376756+00
0927faeb-60b0-4ad8-86a6-9a57cc1793a5	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	879	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:29:46.076658+00	2025-12-19 15:29:46.076658+00
371803e0-4529-403b-8e81-cb6e59a3c5c7	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	874	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:29:47.639426+00	2025-12-19 15:29:47.639426+00
4a28a866-7e44-439f-a271-21175dd46146	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	879	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:30:31.3545+00	2025-12-19 15:30:31.3545+00
a1809719-55bd-4336-855f-c860074ec3a6	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	874	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:30:32.301603+00	2025-12-19 15:30:32.301603+00
5ae330bb-c4b6-4303-a6be-d975843ff0ad	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	913	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:32:02.701503+00	2025-12-19 15:32:02.701503+00
381fea95-da1d-405f-a743-0fb0ea501b7b	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	914	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:32:05.516455+00	2025-12-19 15:32:05.516455+00
b5f37c9c-72be-42d1-9f93-573848706265	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	915	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:32:21.303568+00	2025-12-19 15:32:21.303568+00
c51e2b52-fcfd-476f-99b2-34d316f44931	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	951	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:33:01.867364+00	2025-12-19 15:33:01.867364+00
9ff7b1ca-7f90-49fa-ab24-72fd193be4c2	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	951	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:33:14.281745+00	2025-12-19 15:33:14.281745+00
bfd9cf93-a500-4f34-b9ac-dd69cc3020f1	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1041	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:35:20.342218+00	2025-12-19 15:35:20.342218+00
839ea266-ccd5-4f25-8e75-3debc70a64e2	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1042	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:35:21.655101+00	2025-12-19 15:35:21.655101+00
95e7e723-1d2e-4773-83c9-3bfb0a0380f7	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1053	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:35:31.465103+00	2025-12-19 15:35:31.465103+00
0621b745-ec87-47fb-a678-5372456522c7	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1090	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:36:28.560998+00	2025-12-19 15:36:28.560998+00
dd5dbfbe-7982-4c0c-a241-c0a9601d1646	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1094	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:36:34.047749+00	2025-12-19 15:36:34.047749+00
addee51a-80ef-4f94-af9f-39939c79d839	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1099	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:36:39.433345+00	2025-12-19 15:36:39.433345+00
9670f468-67dd-49b0-811e-14a1a3cb71ab	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1094	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:36:44.056919+00	2025-12-19 15:36:44.056919+00
6d3f9195-8d80-403e-b63c-4fedaec11105	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1129	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:38:07.138086+00	2025-12-19 15:38:07.138086+00
5b4356a4-076e-4d70-a2aa-c412b9a5a899	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1149	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:38:33.166417+00	2025-12-19 15:38:33.166417+00
cd199bee-52b1-45e0-a87f-714eae769473	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1153	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:38:44.075695+00	2025-12-19 15:38:44.075695+00
74b54ccb-19c4-4514-af9b-ba4e329e2f78	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1154	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:38:47.086988+00	2025-12-19 15:38:47.086988+00
d9fce4eb-2686-4f0f-9a32-b3e4eb99c4d6	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1173	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:39:06.276674+00	2025-12-19 15:39:06.276674+00
2e512431-f3db-433a-9f0e-c1dedfca9d68	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1174	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:39:07.604701+00	2025-12-19 15:39:07.604701+00
b36fac48-b5c8-458b-8ec7-89c3d7b6001c	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1178	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:39:07.91606+00	2025-12-19 15:39:07.91606+00
88b6ef52-f4d1-46dc-84ec-3fbdb62570ab	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1254	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:40:12.303459+00	2025-12-19 15:40:12.303459+00
0c7a517a-9e1b-4e18-8cba-2fc6d707fc37	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1310	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:40:58.396941+00	2025-12-19 15:40:58.396941+00
4a18d166-bac4-4d31-948b-78d71d71eada	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1256	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:41:03.768161+00	2025-12-19 15:41:03.768161+00
a3f861c3-5117-4758-af35-20b54e072f87	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1318	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:41:04.534913+00	2025-12-19 15:41:04.534913+00
865073f1-34a6-4e86-aa70-4870a6d39532	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1327	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:41:36.668371+00	2025-12-19 15:41:36.668371+00
a737f99a-a5e9-41a4-b522-54f1025175bd	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1323	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:42:20.347365+00	2025-12-19 15:42:20.347365+00
6c7f1e1f-b908-4a7d-bcb7-71ec4757f372	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1414	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:44:58.660661+00	2025-12-19 15:44:58.660661+00
c4b24a63-5914-46d1-919d-efbf2ddd9be6	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1475	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:47:29.844459+00	2025-12-19 15:47:29.844459+00
a0cd9d67-372f-41a0-a15e-3db2d66e4995	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1475	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:47:40.003817+00	2025-12-19 15:47:40.003817+00
18047647-f73f-4bd6-97d2-fc99bff38bf9	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1484	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:47:51.614763+00	2025-12-19 15:47:51.614763+00
00ee9d90-e712-4d1f-a7e5-5f30ff1a97df	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1515	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:48:14.556456+00	2025-12-19 15:48:14.556456+00
270232ea-f159-4d89-9a68-f727add7e0aa	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1496	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:48:19.523522+00	2025-12-19 15:48:19.523522+00
921bac58-2cc5-446d-9c4e-c39a6a52b801	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1549	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:49:07.604971+00	2025-12-19 15:49:07.604971+00
7aa859f9-c2c9-459a-8a3b-5dcc16a4d378	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1581	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:50:32.456601+00	2025-12-19 15:50:32.456601+00
4c116fdd-d0cf-4a52-b84e-ab151fdc835d	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1596	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:51:36.893422+00	2025-12-19 15:51:36.893422+00
c72819fc-153f-47fe-a36d-8172e5901303	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1599	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:51:41.016635+00	2025-12-19 15:51:41.016635+00
8e8dc530-33ae-465a-aba3-48e6c06ecb52	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1625	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:53:04.771169+00	2025-12-19 15:53:04.771169+00
c45c6ff9-4450-4a18-83f6-70f2a243459d	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1645	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:53:56.900861+00	2025-12-19 15:53:56.900861+00
85898e9e-1ae9-476a-82c8-5d79ae292c2b	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1666	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:54:40.534319+00	2025-12-19 15:54:40.534319+00
7e57a4c9-503c-4580-8f9c-a174d2aaf980	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1730	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:55:54.799592+00	2025-12-19 15:55:54.799592+00
f8aa6135-b63b-48ba-a8be-ddc61b6b8052	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1732	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:55:57.068548+00	2025-12-19 15:55:57.068548+00
5ada1642-fbb0-485b-9853-9dc5e54b1e7a	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1760	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:56:16.581504+00	2025-12-19 15:56:16.581504+00
d3508d75-c909-41e5-8087-26a8c23e7300	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1798	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:56:57.496033+00	2025-12-19 15:56:57.496033+00
fb1b1b36-bc0e-4d47-8452-42a8c20dccba	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1853	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:58:37.939393+00	2025-12-19 15:58:37.939393+00
6e42c884-3acb-48a2-a04b-5813ed0183f9	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1853	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:58:49.502047+00	2025-12-19 15:58:49.502047+00
7f405770-9166-43ca-a6e1-79d16bd69537	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1853	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:59:00.670349+00	2025-12-19 15:59:00.670349+00
dea60402-97dc-455c-ac83-59eb4b5a8714	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1868	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:59:02.597432+00	2025-12-19 15:59:02.597432+00
31992749-ec3a-4c33-8a34-e45b4aff79bd	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1853	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:59:10.706931+00	2025-12-19 15:59:10.706931+00
62d4e8dd-054c-4f65-84dc-9175e218dd8f	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1853	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:59:22.665563+00	2025-12-19 15:59:22.665563+00
bd764f5c-5b99-47d2-a26b-0a4323d1f3ef	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1853	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:59:34.633383+00	2025-12-19 15:59:34.633383+00
456249b7-84e8-4044-ac7a-867a0029fb36	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1853	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 15:59:46.150905+00	2025-12-19 15:59:46.150905+00
5c158fa3-11b0-49a6-a93b-7208a7ac171b	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1931	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:01:27.022727+00	2025-12-19 16:01:27.022727+00
38fda3f6-1c20-4156-8755-ea7d6ba6cf7f	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1931	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:01:47.400499+00	2025-12-19 16:01:47.400499+00
8f9c8ae0-a604-4323-a9b9-5da411287ffa	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1954	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:02:11.441+00	2025-12-19 16:02:11.441+00
096e4427-101f-44d4-9fda-4f45c0013dbd	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	1963	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:02:37.924442+00	2025-12-19 16:02:37.924442+00
8907ff8b-d0b1-4879-86e9-75db81c473c0	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2023	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:04:45.202334+00	2025-12-19 16:04:45.202334+00
a4a84fc1-0ca6-4a63-89e7-0ddf4d4929a5	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2025	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:04:48.529351+00	2025-12-19 16:04:48.529351+00
e8e28f59-f63a-4696-831d-fd0f11f02957	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2149	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:08:56.197796+00	2025-12-19 16:08:56.197796+00
c0f1cbf6-f66c-403b-8bf2-44fb3d1e84e6	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2234	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:10:46.184565+00	2025-12-19 16:10:46.184565+00
707a01d9-1389-47d5-98c0-42d56bff3613	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2233	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:11:24.786128+00	2025-12-19 16:11:24.786128+00
db722e27-3f72-4491-84a0-6ba33c38b364	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2260	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:11:28.402599+00	2025-12-19 16:11:28.402599+00
85566d35-88f2-4378-98ce-3f08f1cb8639	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2277	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:11:55.016885+00	2025-12-19 16:11:55.016885+00
fc8d7152-f2ae-4ab1-a7cd-7c3d2a147c07	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2342	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:12:49.295642+00	2025-12-19 16:12:49.295642+00
56edc7e6-087e-4085-88a2-cb3dc65585f9	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2342	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:13:07.224976+00	2025-12-19 16:13:07.224976+00
33404835-f8ba-4f5c-9f6d-f7a571ee2f34	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2407	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:15:47.207136+00	2025-12-19 16:15:47.207136+00
a9e80259-bf2b-4900-8ec2-c14f2147b750	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2408	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:15:48.982244+00	2025-12-19 16:15:48.982244+00
b51bb5d3-3f8b-42e5-9e96-c15da577e56c	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2470	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:17:29.087503+00	2025-12-19 16:17:29.087503+00
365cceb1-de19-4b0e-9b28-82cc14dc5b95	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2528	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:19:43.857388+00	2025-12-19 16:19:43.857388+00
76073d4d-eb0a-4493-9131-3b2d58a550e5	cc9a1778-56aa-4bad-9b68-7a8ec5b5c316	\N	intrusion	2608	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:23:55.301026+00	2025-12-19 16:23:55.301026+00
814911ea-82df-499c-a8db-ed121ccb9e71	cc9a1778-56aa-4bad-9b68-7a8ec5b5c316	\N	intrusion	2608	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:24:05.306887+00	2025-12-19 16:24:05.306887+00
788f3e08-ce2b-418b-8a5f-179ce7fdcf43	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2621	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:25:20.525717+00	2025-12-19 16:25:20.525717+00
fa1b0f49-443a-480f-b6e4-7eb1b2af220e	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2628	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:25:22.060522+00	2025-12-19 16:25:22.060522+00
66e6dcca-83ae-4ba7-9f83-79e483b81a97	cc9a1778-56aa-4bad-9b68-7a8ec5b5c316	\N	intrusion	2629	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:25:27.33853+00	2025-12-19 16:25:27.33853+00
139fc912-8933-4a1c-b594-f9a1c21d5194	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2647	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:26:25.19178+00	2025-12-19 16:26:25.19178+00
e7dd29b5-3853-4323-b033-9910e1df96e5	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2646	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:26:26.291118+00	2025-12-19 16:26:26.291118+00
0603276f-73de-46b4-aace-5715bf8ac85f	cc9a1778-56aa-4bad-9b68-7a8ec5b5c316	\N	intrusion	2652	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:27:08.534881+00	2025-12-19 16:27:08.534881+00
aa2abfbe-4b3c-4f0f-9aa0-7c0e7ef7126d	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2715	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:29:19.558069+00	2025-12-19 16:29:19.558069+00
d3fc95f8-4c7f-4aab-b2d2-e2fd53293733	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2919	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:37:48.350915+00	2025-12-19 16:37:48.350915+00
8772d9aa-30f4-4ccf-9f4d-80a8561844e8	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	2967	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:39:09.266613+00	2025-12-19 16:39:09.266613+00
d7770289-3a36-415e-9a87-ab2a6d1ddfa2	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3005	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:40:10.386874+00	2025-12-19 16:40:10.386874+00
684500b2-7edd-49d3-a7ef-c337f9589e2b	cc9a1778-56aa-4bad-9b68-7a8ec5b5c316	\N	intrusion	3038	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:41:15.221646+00	2025-12-19 16:41:15.221646+00
29e53c7d-7043-448f-9b8d-0be90e18974f	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3046	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:41:40.028503+00	2025-12-19 16:41:40.028503+00
75f78d4d-4cc8-4b09-90b9-5eb452faab49	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3094	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:45:35.330812+00	2025-12-19 16:45:35.330812+00
e7faa734-de28-4b53-acb5-88f03d247be5	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3139	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:47:42.8676+00	2025-12-19 16:47:42.8676+00
22b62aee-4b84-4a8d-b522-0db2e9648c09	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3165	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:51:08.092208+00	2025-12-19 16:51:08.092208+00
ef1970e1-5f6a-4c4c-bac7-3844dd4c1743	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3194	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:51:29.595164+00	2025-12-19 16:51:29.595164+00
befc6986-3179-4742-a7a3-8234450bb2b6	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3194	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:51:41.782367+00	2025-12-19 16:51:41.782367+00
9a80f00b-380c-42c4-afe8-f42674feaceb	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3194	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:51:58.559222+00	2025-12-19 16:51:58.559222+00
d65b69a6-4ab1-432a-9ca6-f679bc2f5205	cc9a1778-56aa-4bad-9b68-7a8ec5b5c316	\N	intrusion	3241	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:52:35.88623+00	2025-12-19 16:52:35.88623+00
3b7fc6b5-fcbe-4b5f-afcb-3fc025ba7977	cc9a1778-56aa-4bad-9b68-7a8ec5b5c316	\N	intrusion	3241	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:52:46.748588+00	2025-12-19 16:52:46.748588+00
2bbbecbc-ca1f-4f84-a0d7-46c67819a8ea	cc9a1778-56aa-4bad-9b68-7a8ec5b5c316	\N	intrusion	3241	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:52:57.848277+00	2025-12-19 16:52:57.848277+00
7ece4c79-2760-4528-a4e8-60ef2ad51a2b	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3264	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:53:19.852884+00	2025-12-19 16:53:19.852884+00
76135dab-990b-429a-bfb0-51ac90f25244	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3267	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:53:28.92953+00	2025-12-19 16:53:28.92953+00
812e5972-2453-421c-b4c5-6fb0dd26a526	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3269	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:53:32.340957+00	2025-12-19 16:53:32.340957+00
30474b5f-1df4-45f6-94da-40c4588c26e4	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3277	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:53:48.453881+00	2025-12-19 16:53:48.453881+00
ead403e0-1edf-4bc4-886c-62e4eedd954e	cc9a1778-56aa-4bad-9b68-7a8ec5b5c316	\N	intrusion	3278	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:54:06.363996+00	2025-12-19 16:54:06.363996+00
ccf1b052-46ca-4a2d-9618-15e0f3d7635b	cc9a1778-56aa-4bad-9b68-7a8ec5b5c316	\N	intrusion	3278	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:56:57.765703+00	2025-12-19 16:56:57.765703+00
5db05251-eecf-4a3d-807a-e0989131d46b	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3355	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:57:50.24803+00	2025-12-19 16:57:50.24803+00
d67a9af9-0e66-4062-a43e-9a5189949530	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3383	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 16:59:32.148982+00	2025-12-19 16:59:32.148982+00
2f6a2c02-7334-414c-bbed-204c817892ee	cc9a1778-56aa-4bad-9b68-7a8ec5b5c316	\N	intrusion	3278	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:00:48.318921+00	2025-12-19 17:00:48.318921+00
27013fd3-8d60-4cc3-aab8-962f66daa39c	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3439	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:02:19.063701+00	2025-12-19 17:02:19.063701+00
b1bf7b13-c49d-4aa4-99e9-84f7a4f86f8e	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3497	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:04:31.14932+00	2025-12-19 17:04:31.14932+00
06eb8a75-8b3b-4742-a653-12c86111f970	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3498	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:04:39.333658+00	2025-12-19 17:04:39.333658+00
b58f7680-fa17-4113-b445-11855bbd0817	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3539	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:06:36.79233+00	2025-12-19 17:06:36.79233+00
4307e19e-65db-4e80-aa0d-838c5484ee76	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3563	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:07:11.125567+00	2025-12-19 17:07:11.125567+00
00b90967-5803-4566-bfae-3d35a64b9a25	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3564	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:07:13.194221+00	2025-12-19 17:07:13.194221+00
88df102c-3939-4e5e-9480-7063c23b3284	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3563	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:07:31.390066+00	2025-12-19 17:07:31.390066+00
22d2d13f-3005-45d5-aa6b-26a71fd67f6c	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3579	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:07:32.110641+00	2025-12-19 17:07:32.110641+00
c9095c95-3877-4ea5-a5e8-dd169dad2131	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3631	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:08:22.323399+00	2025-12-19 17:08:22.323399+00
f295ca02-12da-462f-ad0a-b0bc2083fcda	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3635	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:08:26.498895+00	2025-12-19 17:08:26.498895+00
1600feef-990d-499c-af00-f361ee731705	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3712	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:11:55.397411+00	2025-12-19 17:11:55.397411+00
2ffd3244-d2e2-470d-9e58-ceb7d2adb562	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3734	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:13:19.416129+00	2025-12-19 17:13:19.416129+00
e3bee0b3-7bfb-4325-bfcf-5127da6bcdf8	cc9a1778-56aa-4bad-9b68-7a8ec5b5c316	\N	intrusion	3278	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:13:43.729241+00	2025-12-19 17:13:43.729241+00
8581594d-83bc-43df-9d45-601f55e9f048	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3742	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:13:52.703882+00	2025-12-19 17:13:52.703882+00
35412504-4fab-44f9-9cd1-b0a5f68bdb55	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3747	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:14:14.391088+00	2025-12-19 17:14:14.391088+00
81067c1d-57a2-4d5b-9b52-715f2ca91128	1440355a-412f-41fe-a430-8f6b0390f27b	\N	intrusion	3749	\N	\N	\N	\N	HIGH	PENDING	2025-12-19 17:14:16.306713+00	2025-12-19 17:14:16.306713+00
\.


--
-- Data for Name: faces; Type: TABLE DATA; Schema: public; Owner: user
--

COPY public.faces (id, name, created_at) FROM stdin;
\.


--
-- Data for Name: permissions; Type: TABLE DATA; Schema: public; Owner: user
--

COPY public.permissions (id, slug, description) FROM stdin;
\.


--
-- Data for Name: role_permissions; Type: TABLE DATA; Schema: public; Owner: user
--

COPY public.role_permissions (role_id, permission_id) FROM stdin;
\.


--
-- Data for Name: roles; Type: TABLE DATA; Schema: public; Owner: user
--

COPY public.roles (id, code, name, description, is_system_role) FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: user
--

COPY public.users (id, username, email, password_hash, role_id, full_name, is_active, last_login, created_at, updated_at) FROM stdin;
\.


--
-- Name: faces_id_seq; Type: SEQUENCE SET; Schema: public; Owner: user
--

SELECT pg_catalog.setval('public.faces_id_seq', 1, false);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: camera_ai_configs camera_ai_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.camera_ai_configs
    ADD CONSTRAINT camera_ai_configs_pkey PRIMARY KEY (id);


--
-- Name: cameras cameras_pkey; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.cameras
    ADD CONSTRAINT cameras_pkey PRIMARY KEY (id);


--
-- Name: event_actions event_actions_pkey; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.event_actions
    ADD CONSTRAINT event_actions_pkey PRIMARY KEY (id);


--
-- Name: events events_pkey; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_pkey PRIMARY KEY (id);


--
-- Name: faces faces_pkey; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.faces
    ADD CONSTRAINT faces_pkey PRIMARY KEY (id);


--
-- Name: permissions permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_pkey PRIMARY KEY (id);


--
-- Name: permissions permissions_slug_key; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.permissions
    ADD CONSTRAINT permissions_slug_key UNIQUE (slug);


--
-- Name: role_permissions role_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (role_id, permission_id);


--
-- Name: roles roles_code_key; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_code_key UNIQUE (code);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: audit_logs audit_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: camera_ai_configs camera_ai_configs_camera_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.camera_ai_configs
    ADD CONSTRAINT camera_ai_configs_camera_id_fkey FOREIGN KEY (camera_id) REFERENCES public.cameras(id) ON DELETE CASCADE;


--
-- Name: event_actions event_actions_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.event_actions
    ADD CONSTRAINT event_actions_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.events(id) ON DELETE CASCADE;


--
-- Name: event_actions event_actions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.event_actions
    ADD CONSTRAINT event_actions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: events events_camera_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_camera_id_fkey FOREIGN KEY (camera_id) REFERENCES public.cameras(id) ON DELETE SET NULL;


--
-- Name: events events_config_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_config_id_fkey FOREIGN KEY (config_id) REFERENCES public.camera_ai_configs(id);


--
-- Name: role_permissions role_permissions_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(id) ON DELETE CASCADE;


--
-- Name: role_permissions role_permissions_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: users users_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: user
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id);


--
-- PostgreSQL database dump complete
--

\unrestrict fidGOcFysbnLvs7rLB3Cf2N8w54bMYbzvNZ2tjHugdcE5Hd00FCvAO9fzPjjWLf

