-- Limit enumeration of server-only character profiles through editable surnames.
CREATE TABLE IF NOT EXISTS app_surname_queries (
    owner text NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    query_day date NOT NULL,
    surname text NOT NULL CHECK (char_length(surname) BETWEEN 1 AND 4),
    PRIMARY KEY (owner, query_day, surname)
);
