import os
import secrets
from datetime import datetime

import pymysql
from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from db import get_connection


app = Flask(__name__)

app.secret_key = os.environ["FLASK_SECRET_KEY"]

@app.get("/")
def polling_unit_results():
    selected_id = request.args.get("polling_unit", type=int)
    results = []
    selected_unit = None

    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT uniqueid, polling_unit_name
                FROM polling_unit
                ORDER BY polling_unit_name, uniqueid
            """)
            polling_units = cursor.fetchall()

            if selected_id is not None:
                cursor.execute("""
                    SELECT uniqueid, polling_unit_name
                    FROM polling_unit
                    WHERE uniqueid = %s
                """, (selected_id,))
                selected_unit = cursor.fetchone()

                if selected_unit is not None:
                    cursor.execute("""
                        SELECT party_abbreviation, party_score
                        FROM announced_pu_results
                        WHERE polling_unit_uniqueid = %s
                        ORDER BY party_abbreviation
                    """, (str(selected_id),))
                    results = cursor.fetchall()
    finally:
        connection.close()

    return render_template(
        "polling_unit.html",
        polling_units=polling_units,
        selected_id=selected_id,
        selected_unit=selected_unit,
        results=results,
    )

@app.get("/lga-results")
def lga_results():
    selected_lga_id = request.args.get("lga", type=int)
    selected_lga = None
    results = []

    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT lga_id, lga_name
                FROM lga
                WHERE state_id = 25
                ORDER BY lga_name
            """)
            lgas = cursor.fetchall()

            if selected_lga_id is not None:
                cursor.execute("""
                    SELECT lga_id, lga_name
                    FROM lga
                    WHERE lga_id = %s AND state_id = 25
                """, (selected_lga_id,))
                selected_lga = cursor.fetchone()

                if selected_lga is not None:
                    cursor.execute("""
                        SELECT
                            results.party_abbreviation,
                            SUM(results.party_score) AS total_votes
                        FROM announced_pu_results AS results
                        JOIN polling_unit AS unit
                            ON results.polling_unit_uniqueid =
                               CAST(unit.uniqueid AS CHAR)
                        WHERE unit.lga_id = %s
                        GROUP BY results.party_abbreviation
                        ORDER BY results.party_abbreviation
                    """, (selected_lga_id,))
                    results = cursor.fetchall()
    finally:
        connection.close()

    return render_template(
        "lga_results.html",
        lgas=lgas,
        selected_lga_id=selected_lga_id,
        selected_lga=selected_lga,
        results=results,
    )

@app.route("/new-results", methods=["GET", "POST"])
def new_results():
    selected_lga_id = request.values.get("lga", type=int)
    errors = []
    wards = []

    if "form_token" not in session:
        session["form_token"] = secrets.token_hex(32)

    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT lga_id, lga_name
                FROM lga
                WHERE state_id = 25
                ORDER BY lga_name
            """)
            lgas = cursor.fetchall()

            valid_lga_ids = [lga["lga_id"] for lga in lgas]

            if selected_lga_id in valid_lga_ids:
                cursor.execute("""
                    SELECT uniqueid, ward_id, ward_name
                    FROM ward
                    WHERE lga_id = %s
                    ORDER BY ward_name, uniqueid
                """, (selected_lga_id,))
                wards = cursor.fetchall()

            cursor.execute("""
                SELECT partyid, partyname
                FROM party
                ORDER BY id
            """)
            parties = cursor.fetchall()

            if request.method == "POST":
                submitted_token = request.form.get("form_token", "")

                if not secrets.compare_digest(
                    submitted_token, session["form_token"]
                ):
                    abort(400, description="Invalid form. Reload and try again.")

                name = request.form.get("polling_unit_name", "").strip()
                entered_by = request.form.get("entered_by", "").strip()
                selected_ward_id = request.form.get("ward", type=int)

                selected_ward = None

                for ward in wards:
                    if ward["uniqueid"] == selected_ward_id:
                        selected_ward = ward
                        break

                if selected_lga_id not in valid_lga_ids:
                    errors.append("Choose a valid Delta State LGA.")

                if selected_ward is None:
                    errors.append("Choose a ward belonging to that LGA.")

                if not name or len(name) > 50:
                    errors.append(
                        "Polling unit name must contain 1 to 50 characters."
                    )

                if not entered_by or len(entered_by) > 50:
                    errors.append(
                        "Your name must contain 1 to 50 characters."
                    )

                scores = {}

                for party in parties:
                    party_id = party["partyid"]
                    value = request.form.get(
                        f"score_{party_id}", ""
                    ).strip()

                    if (
                        not value
                        or not value.isascii()
                        or not value.isdecimal()
                        or len(value) > 10
                    ):
                        errors.append(
                            f"Enter a non-negative whole number for {party_id}."
                        )
                        continue

                    score = int(value)

                    if score > 2147483647:
                        errors.append(f"The score for {party_id} is too large.")
                    else:
                        scores[party_id] = score

                if not errors:
                    try:
                        connection.begin()

                        # Serialize new-unit numbering within this LGA.
                        cursor.execute("""
                            SELECT uniqueid
                            FROM lga
                            WHERE lga_id = %s AND state_id = 25
                            FOR UPDATE
                        """, (selected_lga_id,))

                        cursor.execute("""
                            SELECT COALESCE(MAX(polling_unit_id), 0) + 1
                                AS next_id
                            FROM polling_unit
                            WHERE lga_id = %s AND ward_id = %s
                        """, (
                            selected_lga_id,
                            selected_ward["ward_id"],
                        ))
                        next_id = cursor.fetchone()["next_id"]

                        polling_number = "NEW-" + secrets.token_hex(8)
                        date_entered = datetime.now()
                        user_ip = request.remote_addr or "unknown"

                        cursor.execute("""
                            INSERT INTO polling_unit (
                                polling_unit_id,
                                ward_id,
                                lga_id,
                                uniquewardid,
                                polling_unit_number,
                                polling_unit_name,
                                entered_by_user,
                                date_entered,
                                user_ip_address
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            next_id,
                            selected_ward["ward_id"],
                            selected_lga_id,
                            selected_ward["uniqueid"],
                            polling_number,
                            name,
                            entered_by,
                            date_entered,
                            user_ip,
                        ))

                        new_unit_id = cursor.lastrowid

                        for party_id, score in scores.items():
                            cursor.execute("""
                                INSERT INTO announced_pu_results (
                                    polling_unit_uniqueid,
                                    party_abbreviation,
                                    party_score,
                                    entered_by_user,
                                    date_entered,
                                    user_ip_address
                                )
                                VALUES (%s, %s, %s, %s, %s, %s)
                            """, (
                                str(new_unit_id),
                                party_id,
                                score,
                                entered_by,
                                date_entered,
                                user_ip,
                            ))

                        connection.commit()

                    except pymysql.Error:
                        connection.rollback()
                        app.logger.exception("Could not save polling-unit results")
                        errors.append(
                            "The results could not be saved. Please try again."
                        )
                    else:
                        # Prevent an immediate repeat submission of this form.
                        session["form_token"] = secrets.token_hex(32)

                        return redirect(url_for(
                            "polling_unit_results",
                            polling_unit=new_unit_id,
                        ))

        return render_template(
            "new_results.html",
            lgas=lgas,
            wards=wards,
            parties=parties,
            selected_lga_id=selected_lga_id,
            errors=errors,
            form_token=session["form_token"],
        )
    finally:
        connection.close()