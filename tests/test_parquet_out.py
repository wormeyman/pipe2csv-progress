import datetime

import pyarrow as pa
import pyarrow.parquet as pq

from vrdb import parquet_out, reader, schema


def test_arrow_schema_types():
    fields = {f.name: f.type for f in parquet_out.arrow_schema(schema.VOTERS)}
    assert fields["StateVoterID"] == pa.int64()
    assert fields["Birthyear"] == pa.int64()
    assert fields["Registrationdate"] == pa.date32()
    assert fields["LastVoted"] == pa.date32()
    assert fields["RegZipCode"] == pa.string()
    assert fields["PrecinctPart"] == pa.string()


def test_write_and_read_back(tmp_path, vrdb_txt):
    out = tmp_path / "voters.parquet"
    n = parquet_out.write_batches(
        out, schema.VOTERS, reader.iter_batches(vrdb_txt, schema.VOTERS)
    )
    assert n == 10
    table = pq.read_table(out)
    assert table.num_rows == 10
    assert table.schema.field("Registrationdate").type == pa.date32()


def test_dates_arrive_as_real_dates(tmp_path, vrdb_txt):
    out = tmp_path / "voters.parquet"
    parquet_out.write_batches(
        out, schema.VOTERS, reader.iter_batches(vrdb_txt, schema.VOTERS)
    )
    table = pq.read_table(out).to_pydict()
    index = table["StateVoterID"].index(9000001)
    assert table["Registrationdate"][index] == datetime.date(2018, 5, 1)


def test_nulls_survive(tmp_path, vrdb_txt):
    out = tmp_path / "voters.parquet"
    parquet_out.write_batches(
        out, schema.VOTERS, reader.iter_batches(vrdb_txt, schema.VOTERS)
    )
    data = pq.read_table(out).to_pydict()
    index = data["StateVoterID"].index(9000003)
    assert data["Birthyear"][index] is None
    assert data["Gender"][index] is None
    assert data["LastVoted"][index] is None
    assert all(v is None for v in data["Mail3"])


def test_identifier_columns_stay_strings(tmp_path, vrdb_txt):
    out = tmp_path / "voters.parquet"
    parquet_out.write_batches(
        out, schema.VOTERS, reader.iter_batches(vrdb_txt, schema.VOTERS)
    )
    data = pq.read_table(out).to_pydict()
    index = data["StateVoterID"].index(9000004)
    assert data["PrecinctCode"][index] == "0600"
    assert data["PrecinctPart"][index] == "0600.919"


def test_multiple_batches_produce_multiple_row_groups(tmp_path, vrdb_txt):
    out = tmp_path / "voters.parquet"
    parquet_out.write_batches(
        out, schema.VOTERS, reader.iter_batches(vrdb_txt, schema.VOTERS, batch_size=4)
    )
    assert pq.ParquetFile(out).num_row_groups == 3
    assert pq.read_table(out).num_rows == 10


def test_empty_input_still_writes_a_valid_file(tmp_path):
    out = tmp_path / "empty.parquet"
    n = parquet_out.write_batches(out, schema.VOTERS, iter([]))
    assert n == 0
    assert pq.read_table(out).num_rows == 0
