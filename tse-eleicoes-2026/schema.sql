-- Banco SQLite com os dados das eleições presidenciais de 2026 (TSE).

-- Uma linha por seção eleitoral/turno, extraída do log da urna (logd.dat dentro do .logjez).
CREATE TABLE IF NOT EXISTS secao (
    turno          INTEGER NOT NULL,
    uf             TEXT    NOT NULL,
    cd_municipio   INTEGER NOT NULL,
    nr_zona        INTEGER NOT NULL,
    nr_secao       INTEGER NOT NULL,
    votos_total    INTEGER NOT NULL,   -- linhas "O voto do eleitor foi computado" no dia da eleição
    primeiro_voto  TEXT,               -- HH:MM:SS no relógio da urna
    ultimo_voto    TEXT,               -- HH:MM:SS no relógio da urna
    PRIMARY KEY (turno, uf, cd_municipio, nr_zona, nr_secao)
);

-- Votos computados por hora cheia do relógio da urna (hora 17 = 17:00:00 a 17:59:59).
CREATE TABLE IF NOT EXISTS votos_hora (
    turno          INTEGER NOT NULL,
    uf             TEXT    NOT NULL,
    cd_municipio   INTEGER NOT NULL,
    nr_zona        INTEGER NOT NULL,
    nr_secao       INTEGER NOT NULL,
    hora           INTEGER NOT NULL,
    votos          INTEGER NOT NULL,
    PRIMARY KEY (turno, uf, cd_municipio, nr_zona, nr_secao, hora)
);

-- Arquivos já processados (permite retomar a carga).
CREATE TABLE IF NOT EXISTS carga (
    turno        INTEGER NOT NULL,
    uf           TEXT    NOT NULL,
    arquivos     INTEGER NOT NULL,
    erros        INTEGER NOT NULL,
    concluido_em TEXT    NOT NULL,
    PRIMARY KEY (turno, uf)
);

-- Diferença (em horas) entre o horário de Brasília e o relógio das urnas de cada município,
-- detectada a partir do horário do primeiro voto (abertura às 8h de Brasília).
CREATE TABLE IF NOT EXISTS fuso_municipio (
    turno        INTEGER NOT NULL,
    uf           TEXT    NOT NULL,
    cd_municipio INTEGER NOT NULL,
    offset_h     INTEGER NOT NULL,     -- hora_brasilia = hora_urna + offset_h
    PRIMARY KEY (turno, uf, cd_municipio)
);

-- Votação por seção para Presidente (arquivo votacao_secao_<ano>_BR do Portal de Dados Abertos).
CREATE TABLE IF NOT EXISTS votacao_secao (
    turno              INTEGER,
    uf                 TEXT,
    cd_municipio       INTEGER,
    nm_municipio       TEXT,
    nr_zona            INTEGER,
    nr_secao           INTEGER,
    cd_cargo           INTEGER,
    nr_votavel         INTEGER,
    nm_votavel         TEXT,
    qt_votos           INTEGER,
    qt_aptos           INTEGER,
    qt_comparecimento  INTEGER,
    qt_abstencoes      INTEGER
);
CREATE INDEX IF NOT EXISTS ix_votacao_secao
    ON votacao_secao (turno, uf, cd_municipio, nr_zona, nr_secao);
