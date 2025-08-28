from flask import Flask, render_template, request, redirect, url_for, flash,session
from flask_mysqldb import MySQL
import os



from datetime import date



app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.urandom(24)

# MySQL connection config
app.config['MYSQL_HOST']     = 'localhost'
app.config['MYSQL_USER']     = 'root'
app.config['MYSQL_PASSWORD'] = '0000'
app.config['MYSQL_DB']       = 'espresso_shot_db'

mysql = MySQL(app)






@app.route('/')
def home():
    # Get logged-in user info from session
    user_id = session.get('user_id')

    branch_address = "Ramallah"  # default/fallback
    menu_items = []

    cur = mysql.connection.cursor()

    # Fetch menu items from database
    cur.execute("SELECT mName, Description, menuPrice FROM menu_item")
    menu_items = cur.fetchall()

    if user_id:
        # Get employee id linked to user
        cur.execute("SELECT Employee_ID FROM users WHERE User_ID = %s", (user_id,))
        emp = cur.fetchone()

        if emp:
            employee_id = emp[0]

            # Get branch address based on employee's branch
            cur.execute("""
                SELECT b.Location AS Address
                FROM branch b
                JOIN employee e ON b.Branch_ID = e.Branch_ID
                WHERE e.Employee_ID = %s
            """, (employee_id,))
            result = cur.fetchone()
            if result:
                branch_address = branch_address +" " +result[0]

    cur.close()

    return render_template('home.html', branch_address=branch_address, menu=menu_items)







@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT password, User_ID FROM users WHERE username = %s",
            (username,)
        )
        result = cur.fetchone()

        if result and result[0] == password:
            session['user_id'] = result[1]
            flash('Logged in successfully!', 'success')

            # Employee check
            cur.execute(
                "SELECT Employee_ID FROM users WHERE User_ID = %s",
                (session['user_id'],)
            )
            emp = cur.fetchone()

            if emp:
                employee_id = emp[0]
                cur.execute(
                    "SELECT Manger_ID FROM employee WHERE Employee_ID = %s",
                    (employee_id,)
                )
                manager = cur.fetchone()
                cur.close()

                if manager and manager[0] is None:
                    # Manager
                    return redirect(url_for('dashboard'))
                else:
                    # Normal employee
                    return redirect(url_for('employee_page'))

            cur.close()
        else:
            flash('Invalid username or password', 'danger')

    return render_template('login.html')


# helpers --------------------------------------------------
def is_logged_in():
    return 'user_id' in session

def get_current_user_id():
    return session.get('user_id')

def get_employee_id(user_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT Employee_ID FROM users WHERE User_ID=%s", (user_id,))
    row = cur.fetchone()
    cur.close()
    return row[0] if row else None
# ----------------------------------------------------------
# ---------- employee dashboard (now GET-only) ----------
@app.route('/employee')
def employee_page():
    if not is_logged_in():
        flash('Please log in first', 'warning')
        return redirect(url_for('login'))

    user_id     = get_current_user_id()
    employee_id = get_employee_id(user_id)
    if not employee_id:
        flash('You are not linked to any employee account.', 'danger')
        return redirect(url_for('home'))

    cur = mysql.connection.cursor()

    # === stats (unchanged) ===
    today = date.today()
    cur.execute("SELECT COUNT(*) FROM orders "
                "WHERE Employee_ID=%s AND DATE(Order_Date)=%s",
                (employee_id, today))
    order_count = cur.fetchone()[0]

    # === pending orders: look in payment table ===
    cur.execute("""
            SELECT
              o.Order_ID,
              c.Customer_Name,
              COALESCE(p.Status, 'pending') AS status,
              SUM(od.Quantity * m.menuPrice) AS total
            FROM orders o
            JOIN customer c     ON c.Customer_ID = o.Customer_ID
            JOIN order_detail od ON od.Order_ID   = o.Order_ID
            JOIN menu_item m     ON m.Menu_Item_ID = od.Menu_Item_ID
            LEFT JOIN payment p  ON p.Order_ID     = o.Order_ID
            WHERE o.Employee_ID = %s
              AND COALESCE(p.Status, 'pending') = 'pending'
            GROUP BY o.Order_ID, c.Customer_Name, status
            ORDER BY o.Order_Date DESC
        """, (employee_id,))
    pending_orders = cur.fetchall()
    cur.close()

    return render_template('emp_page.html',
                           order_count=order_count,
                           pending_orders=pending_orders)

# ---------- add new customer ----------
@app.route('/customer/new', methods=['GET', 'POST'])
def customer_new():
    if request.method == 'POST':
        name    = request.form['name']
        cnumber = request.form['cnumber']

        cur = mysql.connection.cursor()

        # check for duplicate number
        cur.execute("SELECT Customer_ID FROM customer WHERE cnumber = %s", (cnumber,))
        row = cur.fetchone()

        if row:                                # number already in DB
            cur.close()
            flash('Customer number already exists. Select or create another customer.', 'warning')
            return redirect(url_for('employee_page'))     # <-- redirect here

        # insert new customer
        cur.execute("INSERT INTO customer (Customer_Name, cnumber) VALUES (%s,%s)",
                    (name, cnumber))
        cid = cur.lastrowid
        mysql.connection.commit()
        cur.close()

        flash('Customer added. You can place an order now.', 'success')
        return redirect(url_for('order_menu', customer_id=cid))

    return render_template('customer_new.html')


# ---------- find existing customer ----------
@app.route('/customer/find', methods=['GET', 'POST'])
def customer_find():
    results = None
    if request.method == 'POST':
        num = request.form['cnumber']
        cur = mysql.connection.cursor()
        cur.execute("SELECT Customer_ID, Customer_Name, cnumber "
                    "FROM customer WHERE cnumber = %s", (num,))
        rows = cur.fetchall()
        cur.close()

        if len(rows) == 1:                           # unique hit → go order
            return redirect(url_for('order_menu', customer_id=rows[0][0]))

        if len(rows) == 0:                           # nothing found → flash
            flash('Customer number not found.', 'warning')
            return redirect(url_for('customer_find'))

        results = rows                               # ambiguous list

    return render_template('customer_find.html', results=results)



@app.route('/order/mark_paid/<int:order_id>', methods=['POST'])
def mark_paid(order_id):
    cur = mysql.connection.cursor()
    cur.execute("UPDATE payment SET Status='paid' WHERE Order_ID=%s", (order_id,))
    mysql.connection.commit()
    cur.close()
    flash('Order marked as paid.', 'success')
    return redirect(url_for('employee_page'))



# ---------- new-order menu ----------
# ---------- new-order menu ----------
@app.route('/order/<int:customer_id>', methods=['GET', 'POST'])
def order_menu(customer_id):
    # -------- auth ----------
    if not is_logged_in():
        flash('Please log in first', 'warning')
        return redirect(url_for('login'))

    user_id     = get_current_user_id()
    employee_id = get_employee_id(user_id)

    cur = mysql.connection.cursor()

    # -------- POST: create order ----------
    if request.method == 'POST':
        ids  = request.form.getlist('item_id')
        qtys = request.form.getlist('quantity')

        # reject if every qty is zero / blank
        if not any(int(q or 0) for q in qtys):
            flash('Please select at least one item.', 'warning')
            cur.close()
            return redirect(url_for('order_menu', customer_id=customer_id))

        # ---- insert into orders ----
        cur.execute("""
            INSERT INTO orders (Customer_ID, Employee_ID, Order_Date)
            VALUES (%s, %s, NOW())
        """, (customer_id, employee_id))
        oid = cur.lastrowid

        # ---- insert each non-zero line ----
        for iid, q in zip(ids, qtys):
            q = int(q or 0)
            if q:
                cur.execute("""
                    INSERT INTO order_detail (Order_ID, Menu_Item_ID, Quantity)
                    VALUES (%s, %s, %s)
                """, (oid, iid, q))

        mysql.connection.commit()
        cur.close()
        flash('Order saved — please record payment.', 'info')
        return redirect(url_for('payment_page', order_id=oid))

    # -------- GET: show menu grid ----------
    cur.execute("""
        SELECT Menu_Item_ID, mName, Description, menuPrice
        FROM menu_item
    """)
    menu_items = cur.fetchall()
    cur.close()
    return render_template('order_menu.html',
                           customer_id=customer_id,
                           menu_items=menu_items)

# ------------ update order -------------

@app.route('/update_order', methods=['POST'])
def update_order():
    # ---------- auth ----------
    if not is_logged_in():
        flash('Please log in first', 'warning')
        return redirect(url_for('login'))

    user_id     = get_current_user_id()
    employee_id = get_employee_id(user_id)
    if not employee_id:
        flash('You are not linked to any employee account.', 'danger')
        return redirect(url_for('employee_page'))

    # ---------- form data ----------
    order_id      = request.form.get('order_id')
    menu_item_id  = request.form.get('menu_item_id')    # NEW
    quantity      = request.form.get('quantity')

    if not (order_id and menu_item_id and quantity):
        flash('Order ID, item ID and quantity are required.', 'danger')
        return redirect(url_for('employee_page'))

    try:
        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        flash('Quantity must be a positive integer.', 'danger')
        return redirect(url_for('employee_page'))

    cur = mysql.connection.cursor()

    # ---------- ownership check ----------
    cur.execute("SELECT Employee_ID FROM orders WHERE Order_ID=%s", (order_id,))
    row = cur.fetchone()
    if not row:
        flash('Order not found.', 'danger')
        cur.close()
        return redirect(url_for('employee_page'))

    if row[0] != employee_id:
        flash('You do not have permission to update this order.', 'danger')
        cur.close()
        return redirect(url_for('employee_page'))

    # ---------- update ----------
    try:
        cur.execute("""
            UPDATE order_detail
               SET Quantity = %s
             WHERE Order_ID     = %s
               AND Menu_Item_ID = %s
        """, (quantity, order_id, menu_item_id))
        if cur.rowcount == 0:
            flash('That item is not part of the order.', 'danger')
        else:
            mysql.connection.commit()
            flash('Order updated successfully.', 'success')
    except Exception as e:
        flash(f'Error updating order: {e}', 'danger')
    finally:
        cur.close()

    return redirect(url_for('employee_page'))









@app.route('/delete_order', methods=['POST'])
def delete_order():
    if not is_logged_in():
        flash('Please log in first', 'warning')
        return redirect(url_for('login'))

    user_id = get_current_user_id()
    employee_id = get_employee_id(user_id)
    if not employee_id:
        flash('You are not linked to any employee account.', 'danger')
        return redirect(url_for('employee_page'))

    order_id = request.form.get('order_id')

    if not order_id:
        flash('Please provide an order ID to delete', 'danger')
        return redirect(url_for('employee_page'))

    cur = mysql.connection.cursor()

    cur.execute(
        "SELECT employee_id FROM orders WHERE order_id = %s",
        (order_id,)
    )
    row = cur.fetchone()

    if not row:
        flash('Order not found', 'danger')
        cur.close()
        return redirect(url_for('employee_page'))

    if row[0] != employee_id:
        flash('You do not have permission to delete this order', 'danger')
        cur.close()
        return redirect(url_for('employee_page'))

    try:
        cur.execute(
            "DELETE FROM orders WHERE order_id = %s",
            (order_id,)
        )
        mysql.connection.commit()
        flash('Order deleted successfully', 'success')
    except Exception as e:
        flash(f'Error deleting order: {str(e)}', 'danger')
    finally:
        cur.close()

    return redirect(url_for('employee_page'))

@app.route('/customer/manage', methods=['GET', 'POST'])
def customer_manage():
    """
    Step 1: search by customer number.
    Step 2: if found, show edit / delete form.
    """
    # -------- first screen: search form --------
    if request.method == 'GET':
        return render_template('customer_manage.html')

    # -------- POST logic --------
    action   = request.form.get('action')      # 'load', 'update', or 'delete'
    cnumber  = request.form.get('cnumber')
    cur      = mysql.connection.cursor()

    # look up the customer once
    cur.execute("SELECT Customer_ID, Customer_Name, cnumber "
                "FROM customer WHERE cnumber = %s", (cnumber,))
    row = cur.fetchone()

    if not row:
        cur.close()
        flash('Customer number not found.', 'warning')
        return redirect(url_for('customer_manage'))

    cid = row[0]

    # ---------- load ----------
    if action == 'load':
        cur.close()
        return render_template('customer_manage.html', customer=row)

    # ---------- update ----------
    if action == 'update':
        new_name = request.form.get('name')
        cur.execute("UPDATE customer SET Customer_Name=%s WHERE Customer_ID=%s",
                    (new_name, cid))
        mysql.connection.commit()
        cur.close()
        flash('Customer updated successfully.', 'success')
        return redirect(url_for('employee_page'))

    # ---------- delete ----------
    if action == 'delete':
        cur.execute("DELETE FROM customer WHERE Customer_ID=%s", (cid,))
        mysql.connection.commit()
        cur.close()
        flash('Customer deleted.', 'success')
        return redirect(url_for('employee_page'))

    # fallback
    cur.close()
    flash('Invalid action.', 'danger')
    return redirect(url_for('customer_manage'))

def _cancel_order(order_id, cur):
    cur.execute("DELETE FROM payment      WHERE Order_ID=%s",(order_id,))
    cur.execute("DELETE FROM order_detail WHERE Order_ID=%s",(order_id,))
    cur.execute("DELETE FROM orders       WHERE Order_ID=%s",(order_id,))
    mysql.connection.commit()


@app.route('/order/not_completed/<int:order_id>', methods=['POST'])
def mark_not_completed(order_id):
    cur = mysql.connection.cursor()

    # # orders table
    # cur.execute("UPDATE orders SET Status='not-completed' WHERE Order_ID=%s",
    #             (order_id,))

    # payment table (update if exists)
    cur.execute("UPDATE payment SET Status='not-completed' WHERE Order_ID=%s",
                (order_id,))
    # if rowcount==0 there was no payment yet → nothing else to do

    mysql.connection.commit()
    cur.close()
    flash('Order marked not completed.', 'info')
    return redirect(url_for('employee_page'))




# ---------- edit items (update + add) ----------
@app.route('/order/<int:order_id>/edit', methods=['GET', 'POST'])
def edit_order(order_id):
    if not is_logged_in():
        flash('Please log in first', 'warning')
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()

    # ---------- POST (save) ----------
    if request.method == 'POST':
        # 1) update / delete existing lines
        for lid, qty in zip(request.form.getlist('odid'),
                            request.form.getlist('qty')):
            qty_int = int(qty or 0)
            if qty_int == 0:
                cur.execute("DELETE FROM order_detail WHERE Line_ID=%s", (lid,))
            else:
                cur.execute("UPDATE order_detail SET Quantity=%s WHERE Line_ID=%s",
                            (qty_int, lid))

        # 2) add a new line (single pair of inputs)
        new_item = request.form.get('new_item_id')
        new_qty  = request.form.get('new_qty')
        if new_item and new_qty:
            q_int = int(new_qty)
            if q_int:
                cur.execute("""
                    INSERT INTO order_detail (Order_ID, Menu_Item_ID, Quantity)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                      Quantity = Quantity + VALUES(Quantity)
                """, (order_id, new_item, q_int))

        mysql.connection.commit()
        cur.close()
        flash('Order updated.', 'success')
        # Redirect back to *this* page so changes are visible immediately
        return redirect(url_for('edit_order', order_id=order_id))

    # ---------- GET (render) ----------
    cur.execute("""
        SELECT od.Line_ID, m.mName, od.Quantity
        FROM order_detail od
        JOIN menu_item m ON od.Menu_Item_ID = m.Menu_Item_ID
        WHERE od.Order_ID = %s
    """, (order_id,))
    lines = cur.fetchall()

    cur.execute("SELECT Menu_Item_ID, mName FROM menu_item")
    menu_items = cur.fetchall()
    cur.close()

    return render_template('edit_order.html',
                           order_id=order_id,
                           lines=lines,
                           menu_items=menu_items)

# ---------- delete a single line ----------
@app.route('/order_line/<int:line_id>/delete/<int:order_id>', methods=['GET', 'POST'])
def delete_line(line_id, order_id):
    cur = mysql.connection.cursor()

    # 1) Count how many lines this order has
    cur.execute("SELECT COUNT(*) FROM order_detail WHERE Order_ID = %s", (order_id,))
    line_count = cur.fetchone()[0]
    print(line_count)

    if line_count <= 1:
        # If it's the last item, do not delete
        flash('Cannot delete the last item from an order.', 'warning')
        cur.close()
        return redirect(url_for('edit_order', order_id=order_id))

    # 2) Otherwise go ahead and delete this line
    cur.execute("DELETE FROM order_detail WHERE Line_ID = %s", (line_id,))
    mysql.connection.commit()
    cur.close()

    flash('Item removed from order.', 'info')
    return redirect(url_for('edit_order', order_id=order_id))

@app.route('/payment/<int:order_id>', methods=['GET', 'POST'])
def payment_page(order_id):
    # ---------- auth ----------
    if not is_logged_in():
        flash('Please log in first', 'warning')
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()

    # ---------- fetch order total + customer + points ----------
    cur.execute("""
        SELECT o.Customer_ID,
               COALESCE(SUM(od.Quantity * m.menuPrice), 0) AS total
        FROM orders o
        JOIN order_detail od ON o.Order_ID = od.Order_ID
        JOIN menu_item   m   ON od.Menu_Item_ID = m.Menu_Item_ID
        WHERE o.Order_ID = %s
        GROUP BY o.Customer_ID
    """, (order_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        flash('Order not found.', 'danger')
        return redirect(url_for('employee_page'))

    customer_id, total = row
    cur.execute("SELECT Loyalty_Points FROM customer WHERE Customer_ID=%s",
                (customer_id,))
    points = cur.fetchone()[0]

    # ---------- cancel via ?cancel=1 ----------
    if request.args.get('cancel'):
        _cancel_order(order_id, cur)
        flash('Order cancelled.', 'success')
        return redirect(url_for('employee_page'))

    # ---------- POST: save / update payment ----------
    if request.method == 'POST':
        method = request.form['method']      # cash | visa | loyaltypoint
        state  = request.form['state']       # paid | pending

        # ----- loyalty-point guard & adjustment -----
        if method == 'loyaltypoint':
            needed = int(total * 10)
            if points < needed:
                cur.close()
                flash('Not enough loyalty points.', 'danger')
                return redirect(url_for('payment_page', order_id=order_id))
            cur.execute("""UPDATE customer
                              SET Loyalty_Points = Loyalty_Points - %s
                            WHERE Customer_ID = %s""",
                        (needed, customer_id))

        # ----- cash / visa earn points -----
        if method in ('cash', 'visa') and state == 'paid':
            cur.execute("""UPDATE customer
                              SET Loyalty_Points = Loyalty_Points + %s
                            WHERE Customer_ID = %s""",
                        (int(total), customer_id))

        # ----- insert OR update payment row -----
        cur.execute("SELECT Payment_ID FROM payment WHERE Order_ID = %s",
                    (order_id,))
        pay_row = cur.fetchone()

        if pay_row:   # ---------- update existing ----------
            cur.execute("""
                UPDATE payment
                   SET Method      = %s,
                       Payment_Date= NOW(),
                       Amount      = %s,
                       Status      = %s
                 WHERE Payment_ID  = %s
            """, (method, total, state, pay_row[0]))
        else:         # ---------- first payment ----------
            cur.execute("""
                INSERT INTO payment (Order_ID, Method, Payment_Date, Amount, Status)
                VALUES (%s, %s, NOW(), %s, %s)
            """, (order_id, method, total, state))

        # ----- update order status -----
        # cur.execute("UPDATE orders SET Status=%s WHERE Order_ID=%s",
        #             (state, order_id))

        mysql.connection.commit()
        cur.close()
        flash('Payment recorded.', 'success')
        return redirect(url_for('employee_page'))

    # ---------- GET → render page ----------
    cur.close()
    return render_template('payment.html',
                           order_id=order_id,
                           total=total,
                           points=points)



@app.route('/dashboard')
def dashboard():
    cur = mysql.connection.cursor()

    # ———— OVERVIEW STATS ————
    cur.execute("SELECT COUNT(*) FROM customer")
    total_customers = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM orders")
    total_orders = cur.fetchone()[0]

    cur.execute("SELECT IFNULL(SUM(Amount),0) FROM payment WHERE Status='paid'")
    total_revenue = cur.fetchone()[0]



    cur.close()
    return render_template(
        'dashboard.html',
        total_customers             = total_customers,
        total_users                 = total_users,
        total_orders                = total_orders,
        total_revenue               = total_revenue,

    )

@app.route('/user/manage', methods=['GET', 'POST'])
def user_manage():
    if not is_logged_in():
        flash('Please log in first', 'warning')
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    edit_user = None

    if request.method == 'POST':
        action = request.form.get('action')
        uid = request.form.get('user_id')

        if action == 'add':
            uname = request.form['username']
            pwd = request.form['password']
            eid = request.form['employee_id']
            cur.execute("SELECT 1 FROM employee WHERE Employee_ID = %s", (eid,))
            if not cur.fetchone():
                flash(f'Employee ID {eid} does not exist.', 'danger')
            else:
                try:
                    cur.execute(
                        "INSERT INTO users (username, password, Employee_ID) VALUES (%s, %s, %s)",
                        (uname, pwd, eid)
                    )
                    mysql.connection.commit()
                    flash('User added.', 'success')
                except Exception as e:
                    mysql.connection.rollback()
                    flash(f'Error adding user: {e}', 'danger')

        elif action == 'load':
            cur.execute("SELECT User_ID, username, password, Employee_ID FROM users WHERE User_ID = %s", (uid,))
            edit_user = cur.fetchone()

        elif action == 'update':
            uname = request.form['username']
            pwd = request.form['password']
            eid = request.form['employee_id']
            cur.execute("SELECT 1 FROM employee WHERE Employee_ID = %s", (eid,))
            if not cur.fetchone():
                flash(f'Employee ID {eid} does not exist.', 'danger')
            else:
                try:
                    cur.execute(
                        "UPDATE users SET username=%s, password=%s, Employee_ID=%s WHERE User_ID=%s",
                        (uname, pwd, eid, uid)
                    )
                    mysql.connection.commit()
                    flash('User updated.', 'success')
                except Exception as e:
                    mysql.connection.rollback()
                    flash(f'Error updating user: {e}', 'danger')

        elif action == 'delete':
            try:
                cur.execute("DELETE FROM users WHERE User_ID = %s", (uid,))
                mysql.connection.commit()
                flash('User deleted.', 'warning')
            except Exception as e:
                mysql.connection.rollback()
                flash(f'Error deleting user: {e}', 'danger')

    cur.execute("SELECT User_ID, username, Employee_ID FROM users")
    users = cur.fetchall()
    cur.close()

    return render_template('user_manage.html', users=users, edit_user=edit_user)

@app.route('/logout')
def logout():
    # clear the session and send user to login
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


@app.route('/warehouses')
def warehouse_page():
    if not is_logged_in():
        flash('Please log in first.', 'warning')
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT Warehouse_ID, Address FROM warehouse")
    warehouses = cur.fetchall()
    cur.close()
    return render_template('warehouse.html', warehouses=warehouses)



@app.route('/add', methods=['POST'])
def add_warehouse():
    try:
        wid = request.form['Warehouse_ID']
        addr = request.form['Address']
    except Exception as e:
        return f"Form error: {e}", 400

    cur = mysql.connection.cursor()
    try:
        cur.execute("INSERT INTO warehouse (Warehouse_ID, Address) VALUES (%s, %s)", (wid, addr))
        mysql.connection.commit()
        flash(f"Warehouse {wid} added.", "success")
    except Exception as e:
        mysql.connection.rollback()
        flash(f"Failed to add warehouse: {e}", "error")
    cur.close()
    return redirect(url_for('index'))



@app.route('/update/<int:warehouse_id>', methods=['POST'])
def update_warehouse(warehouse_id):
    new_address = request.form['Address']
    cur = mysql.connection.cursor()
    cur.execute("UPDATE warehouse SET Address = %s WHERE Warehouse_ID = %s", (new_address, warehouse_id))
    mysql.connection.commit()
    cur.close()
    flash(f"Warehouse {warehouse_id} updated.", "success")
    return redirect(url_for('index'))




@app.route('/delete/<int:warehouse_id>', methods=['POST'])
def delete_warehouse(warehouse_id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM warehouse WHERE Warehouse_ID = %s", (warehouse_id,))
    mysql.connection.commit()
    cur.close()
    flash(f"Warehouse {warehouse_id} deleted.", "success")
    return redirect(url_for('index'))




# ORDERS STATS
@app.route('/stats/orders')
def stats_orders():
    if not is_logged_in(): return redirect(url_for('login'))

    # Default: last 7 days
    from_date = request.args.get('from', default=str(date.today().replace(day=1)))
    to_date = request.args.get('to', default=str(date.today()))
    cur = mysql.connection.cursor()
    # Orders per day in selected range
    cur.execute("""
          SELECT DATE(Order_Date), COUNT(*)
          FROM orders
          WHERE Order_Date BETWEEN %s AND %s
          GROUP BY DATE(Order_Date)
          ORDER BY DATE(Order_Date)
        """, (from_date, to_date))
    orders_per_day = cur.fetchall()
    # Orders by warehouse
    cur.execute("""
      SELECT w.Address, COUNT(o.Order_ID)
      FROM warehouse w
      JOIN branch   b ON b.Warehouse_ID = w.Warehouse_ID
      JOIN employee e ON e.Branch_ID    = b.Branch_ID
      JOIN orders   o ON o.Employee_ID  = e.Employee_ID
      GROUP BY w.Warehouse_ID, w.Address
    """)
    orders_by_warehouse = cur.fetchall()

    # Orders by employee
    cur.execute("""
      SELECT 
        e.Employee_Name,
        COUNT(o.Order_ID) AS Orders_Handled,
        SUM(p.Amount) AS Total_Collected
      FROM employee e
      JOIN orders o ON e.Employee_ID = o.Employee_ID
      JOIN payment p ON p.Order_ID = o.Order_ID
      WHERE p.Status = 'paid'
      GROUP BY e.Employee_ID
      ORDER BY Total_Collected DESC
    """)
    employee_performance = cur.fetchall()

    # Avg order value per customer
    cur.execute("""
        SELECT c.Customer_Name, AVG(od.Quantity * m.menuPrice) AS avg_order_value
        FROM customer c
        JOIN orders o ON o.Customer_ID = c.Customer_ID
        JOIN order_detail od ON od.Order_ID = o.Order_ID
        JOIN menu_item m ON m.Menu_Item_ID = od.Menu_Item_ID
        GROUP BY c.Customer_ID, c.Customer_Name
    """)
    avg_order_value = cur.fetchall()

    # Top 5 customers by revenue
    cur.execute("""
      SELECT c.Customer_Name, SUM(p.Amount)
      FROM customer c
      JOIN orders o ON o.Customer_ID=c.Customer_ID
      JOIN payment p ON p.Order_ID = o.Order_ID
      WHERE p.Status='paid'
      GROUP BY c.Customer_ID, c.Customer_Name
      ORDER BY SUM(p.Amount) DESC
      LIMIT 5
    """)
    top_customers = cur.fetchall()

    # Pending orders count
    cur.execute("""
      SELECT COUNT(*)
      FROM orders o
      LEFT JOIN payment p ON p.Order_ID = o.Order_ID
      WHERE p.Status = 'pending'
    """)
    pending_count = cur.fetchone()[0]


    # Sales by warehouse
    cur.execute("""
      SELECT w.Address, SUM(p.Amount)
      FROM warehouse w
      JOIN branch   b ON b.Warehouse_ID = w.Warehouse_ID
      JOIN employee e ON e.Branch_ID    = b.Branch_ID
      JOIN orders   o ON o.Employee_ID  = e.Employee_ID
      JOIN payment  p ON p.Order_ID     = o.Order_ID
      GROUP BY w.Warehouse_ID, w.Address
    """)
    sales_by_warehouse = cur.fetchall()



    cur.close()
    return render_template('stats_orders.html',
                           orders_by_warehouse=orders_by_warehouse,
                           employee_performance=employee_performance,
                           avg_order_value=avg_order_value,
                           top_customers=top_customers,
                           pending_count=pending_count,
                           sales_by_warehouse=sales_by_warehouse,
                           orders_per_day=orders_per_day,
                           from_date=from_date,
                           to_date=to_date)

# PAYMENT STATS
@app.route('/stats/payments')
def stats_payments():
    if not is_logged_in(): return redirect(url_for('login'))

    # Get optional date range from user
    from_date = request.args.get('from') or str(date.today().replace(day=1))
    to_date = request.args.get('to') or str(date.today())

    cur = mysql.connection.cursor()

    # Payment method distribution (all time — optional to filter too)
    cur.execute("SELECT Method, COUNT(*) FROM payment GROUP BY Method")
    method_dist = cur.fetchall()

    # Total revenue in date range
    cur.execute("""
        SELECT IFNULL(SUM(Amount), 0)
        FROM payment
        WHERE Status = 'paid' AND Payment_Date BETWEEN %s AND %s
    """, (from_date, to_date))
    total_revenue = cur.fetchone()[0]

    # Paid vs Pending count (all time)
    cur.execute("SELECT Status, COUNT(*) FROM payment GROUP BY Status")
    status_counts = cur.fetchall()

    # Revenue by method (filtered)
    cur.execute("""
        SELECT Method, SUM(Amount)
        FROM payment
        WHERE Status = 'paid' AND Payment_Date BETWEEN %s AND %s
        GROUP BY Method
        ORDER BY SUM(Amount) DESC
    """, (from_date, to_date))
    revenue_by_method = cur.fetchall()

    # Daily revenue ( in selected range)
    cur.execute("""
        SELECT Payment_Date, SUM(Amount)
        FROM payment
        WHERE Status = 'paid' AND Payment_Date BETWEEN %s AND %s
        GROUP BY Payment_Date
        ORDER BY Payment_Date
    """, (from_date, to_date))
    daily_revenue = cur.fetchall()

    cur.close()
    return render_template('stats_payments.html',
                           method_dist=method_dist,
                           total_revenue=total_revenue,
                           status_counts=status_counts,
                           revenue_by_method=revenue_by_method,
                           daily_revenue=daily_revenue,
                           from_date=from_date,
                           to_date=to_date)
# CUSTOMER STATS
@app.route('/stats/customers', methods=['GET', 'POST'])
def stats_customers():
    if not is_logged_in(): return redirect(url_for('login'))

    min_orders = request.args.get('min_orders', type=int, default=0)
    max_orders = request.args.get('max_orders', type=int, default=9999)

    cur = mysql.connection.cursor()

    # Customers with order count in given range
    cur.execute("""
        SELECT c.Customer_ID, c.Customer_Name, COUNT(o.Order_ID) AS order_count
        FROM customer c
        LEFT JOIN orders o ON c.Customer_ID = o.Customer_ID
        GROUP BY c.Customer_ID
        HAVING order_count BETWEEN %s AND %s
        ORDER BY order_count DESC
    """, (min_orders, max_orders))
    filtered_customers = cur.fetchall()

    # Loyalty balances
    cur.execute("SELECT Customer_Name, Loyalty_Points FROM customer")
    loyalty = cur.fetchall()

    # Loyalty Points vs Spending (DESC)
    cur.execute("""
        SELECT 
            c.Customer_Name,
            c.Loyalty_Points,
            IFNULL(SUM(p.Amount), 0) AS Total_Spent
        FROM customer c
        LEFT JOIN orders o ON o.Customer_ID = c.Customer_ID
        LEFT JOIN payment p ON p.Order_ID = o.Order_ID AND p.Status = 'paid'
        GROUP BY c.Customer_ID, c.Customer_Name, c.Loyalty_Points
        ORDER BY Loyalty_Points DESC
    """)
    loyalty_vs_spending = cur.fetchall()

    cur.close()

    return render_template('stats_customers.html',
                           filtered_customers=filtered_customers,
                           loyalty=loyalty,
                           loyalty_vs_spending=loyalty_vs_spending,
                           min_orders=min_orders,
                           max_orders=max_orders)






@app.route('/branch_queries')
def branch_queries():
    conn = mysql.connection
    cur = conn.cursor()

    # 1. Top 5 branches by employee count
    cur.execute("""
        SELECT b.Branch_ID, b.Location, COUNT(e.Employee_ID) AS Num_Employees
        FROM branch b
        JOIN employee e ON b.Branch_ID = e.Branch_ID
        GROUP BY b.Branch_ID
        ORDER BY Num_Employees DESC
        LIMIT 5
    """)
    branch_employees = cur.fetchall()
    branch_employees_cols = [desc[0] for desc in cur.description]

    # 2. Branches with pending orders
    cur.execute("""
        SELECT DISTINCT b.Branch_ID, b.Location
        FROM orders o
        JOIN employee e ON o.Employee_ID = e.Employee_ID
        JOIN branch b ON e.Branch_ID = b.Branch_ID
        LEFT JOIN payment p ON o.Order_ID = p.Order_ID
        WHERE COALESCE(p.Status, 'pending') = 'pending'
    """)
    pending_orders = cur.fetchall()
    pending_orders_cols = [desc[0] for desc in cur.description]

    # 3. Branch revenue summary
    cur.execute("""
        SELECT b.Branch_ID, b.Location, 
               ROUND(SUM(od.Quantity * m.menuPrice), 2) AS Revenue
        FROM orders o
        JOIN order_detail od ON o.Order_ID = od.Order_ID
        JOIN menu_item m ON od.Menu_Item_ID = m.Menu_Item_ID
        JOIN employee e ON o.Employee_ID = e.Employee_ID
        JOIN branch b ON e.Branch_ID = b.Branch_ID
        GROUP BY b.Branch_ID, b.Location
        ORDER BY Revenue DESC
    """)
    branch_revenue = cur.fetchall()
    branch_revenue_cols = [desc[0] for desc in cur.description]

    # 4. Top performing branch this month
    cur.execute("""
        SELECT b.Branch_ID, b.Location, 
               ROUND(SUM(od.Quantity * m.menuPrice), 2) AS Revenue
        FROM orders o
        JOIN order_detail od ON o.Order_ID = od.Order_ID
        JOIN menu_item m ON od.Menu_Item_ID = m.Menu_Item_ID
        JOIN employee e ON o.Employee_ID = e.Employee_ID
        JOIN branch b ON e.Branch_ID = b.Branch_ID
        WHERE MONTH(o.Order_Date) = MONTH(CURDATE()) AND YEAR(o.Order_Date) = YEAR(CURDATE())
        GROUP BY b.Branch_ID, b.Location
        ORDER BY Revenue DESC
        LIMIT 1
    """)
    top_branch_month = cur.fetchall()
    top_branch_month_cols = [desc[0] for desc in cur.description]

    # 5. Branches without any orders in the last 30 days
    cur.execute("""
        SELECT b.Branch_ID, b.Location
        FROM branch b
        WHERE b.Branch_ID NOT IN (
            SELECT DISTINCT e.Branch_ID
            FROM orders o
            JOIN employee e ON o.Employee_ID = e.Employee_ID
            WHERE o.Order_Date >= CURDATE() - INTERVAL 30 DAY
        )
    """)
    inactive_branches = cur.fetchall()
    inactive_branches_cols = [desc[0] for desc in cur.description]

    # 6. Branch with highest average order value
    cur.execute("""
        SELECT b.Branch_ID, b.Location,
               ROUND(AVG(order_total.Total), 2) AS Avg_Order_Value
        FROM (
            SELECT o.Order_ID, SUM(od.Quantity * m.menuPrice) AS Total, e.Branch_ID
            FROM orders o
            JOIN order_detail od ON o.Order_ID = od.Order_ID
            JOIN menu_item m ON od.Menu_Item_ID = m.Menu_Item_ID
            JOIN employee e ON o.Employee_ID = e.Employee_ID
            GROUP BY o.Order_ID
        ) AS order_total
        JOIN branch b ON order_total.Branch_ID = b.Branch_ID
        GROUP BY b.Branch_ID
        ORDER BY Avg_Order_Value DESC
        LIMIT 1
    """)
    highest_avg_order_branch = cur.fetchall()
    highest_avg_order_branch_cols = [desc[0] for desc in cur.description]

    # 7. Number of customers served per branch
    cur.execute("""
        SELECT b.Branch_ID, b.Location, COUNT(DISTINCT o.Customer_ID) AS Unique_Customers
        FROM orders o
        JOIN employee e ON o.Employee_ID = e.Employee_ID
        JOIN branch b ON e.Branch_ID = b.Branch_ID
        GROUP BY b.Branch_ID
        ORDER BY Unique_Customers DESC
    """)
    customers_per_branch = cur.fetchall()
    customers_per_branch_cols = [desc[0] for desc in cur.description]

    cur.close()

    return render_template("branch_queries.html",
        branch_employees=branch_employees, branch_employees_cols=branch_employees_cols,
        pending_orders=pending_orders, pending_orders_cols=pending_orders_cols,
        branch_revenue=branch_revenue, branch_revenue_cols=branch_revenue_cols,
        top_branch_month=top_branch_month, top_branch_month_cols=top_branch_month_cols,
        inactive_branches=inactive_branches, inactive_branches_cols=inactive_branches_cols,
        highest_avg_order_branch=highest_avg_order_branch, highest_avg_order_branch_cols=highest_avg_order_branch_cols,
        customers_per_branch=customers_per_branch, customers_per_branch_cols=customers_per_branch_cols
    )


@app.route('/supplier_queries')
def supplier_queries():
    cur = mysql.connection.cursor()

    # 1. Top-rated suppliers (we'll assume "top-rated" by number of supplies instead)
    cur.execute("""
        SELECT sp.Supplier_ID, sp.Supplier_Name, sp.Contact_Info, COUNT(*) AS Total_Supplies
        FROM supplier_product s
        JOIN supplier sp ON s.Supplier_ID = sp.Supplier_ID
        GROUP BY sp.Supplier_ID
        ORDER BY Total_Supplies DESC
        LIMIT 5
    """)
    top_suppliers = cur.fetchall()
    top_suppliers_cols = [desc[0] for desc in cur.description]

    # 2. Total items supplied per supplier
    cur.execute("""
        SELECT sp.Supplier_ID, sp.Supplier_Name, COUNT(s.Product_ID) AS Items_Supplied
        FROM supplier_product s
        JOIN supplier sp ON s.Supplier_ID = sp.Supplier_ID
        GROUP BY sp.Supplier_ID
        ORDER BY Items_Supplied DESC
    """)
    total_supplied = cur.fetchall()
    total_supplied_cols = [desc[0] for desc in cur.description]

    # 3. Suppliers with low supply prices (Supply_Price < 1.0)
    cur.execute("""
        SELECT sp.Supplier_ID, sp.Supplier_Name, p.Product_Name, s.Supply_Price
        FROM supplier_product s
        JOIN supplier sp ON s.Supplier_ID = sp.Supplier_ID
        JOIN product p ON s.Product_ID = p.Product_ID
        WHERE s.Supply_Price < 1.0
        ORDER BY s.Supply_Price ASC
    """)
    low_supply = cur.fetchall()
    low_supply_cols = [desc[0] for desc in cur.description]

    # 4. Supplier contribution value (Supply_Price × #Products)
    cur.execute("""
        SELECT sp.Supplier_ID, sp.Supplier_Name,
               ROUND(SUM(s.Supply_Price), 2) AS Total_Supply_Value
        FROM supplier_product s
        JOIN supplier sp ON s.Supplier_ID = sp.Supplier_ID
        GROUP BY sp.Supplier_ID
        ORDER BY Total_Supply_Value DESC
    """)
    supplier_value = cur.fetchall()
    supplier_value_cols = [desc[0] for desc in cur.description]

    cur.close()
    return render_template("supplier_queries.html",
        top_suppliers=top_suppliers, top_suppliers_cols=top_suppliers_cols,
        total_supplied=total_supplied, total_supplied_cols=total_supplied_cols,
        low_supply=low_supply, low_supply_cols=low_supply_cols,
        supplier_value=supplier_value, supplier_value_cols=supplier_value_cols
    )






@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        employee_id = request.form.get('employee_id')  # Get employee ID from form

        print(username)
        print(password)
        print(employee_id)

        cur = mysql.connection.cursor()

        # Check if username already exists
        cur.execute("SELECT User_ID FROM users WHERE username = %s", (username,))
        existing_user = cur.fetchone()
        if existing_user:
            flash('Username already taken. Please choose another.', 'danger')
            cur.close()
            return render_template('register.html')

        # Check if Employee_ID exists in employee table
        cur.execute("SELECT Employee_ID FROM employee WHERE Employee_ID = %s", (employee_id,))
        valid_employee = cur.fetchone()
        if not valid_employee:
            flash('Employee ID does not exist.', 'danger')
            cur.close()
            return render_template('register.html')

        # Check if Employee_ID is already linked to a user
        cur.execute("SELECT User_ID FROM users WHERE Employee_ID = %s", (employee_id,))
        existingEmployee = cur.fetchone()
        if existingEmployee:
            flash('This employee already has a user account.', 'danger')
            cur.close()
            return render_template('register.html')

        # Insert new user
        cur.execute("INSERT INTO users (username, password, Employee_ID) VALUES (%s, %s, %s)",
                    (username, password, employee_id))
        mysql.connection.commit()
        cur.close()

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')



@app.route('/menu')
def menu_page():
    if not is_logged_in():
        flash('Please log in first.', 'warning')
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT Menu_Item_ID, mName, Description ,menuPrice FROM menu_item")
    menu_items = cur.fetchall()
    cur.close()
    return render_template('menu.html', menu_items=menu_items)


@app.route('/add_menu', methods=['POST'])
def add_menu_item():
    try:
        name = request.form['Name']
        price = request.form['Price']
    except Exception as e:
        return f"Form error: {e}", 400

    cur = mysql.connection.cursor()
    try:
        cur.execute("INSERT INTO menu (Name, Price) VALUES (%s, %s)", (name, price))
        mysql.connection.commit()
        flash(f"Menu item '{name}' added.", "success")
    except Exception as e:
        mysql.connection.rollback()
        flash(f"Failed to add menu item: {e}", "error")
    cur.close()
    return redirect(url_for('menu_page'))


@app.route('/update_menu/<int:menu_id>', methods=['POST'])
def update_menu_item(menu_id):
    new_name = request.form['Name']
    new_price = request.form['Price']

    cur = mysql.connection.cursor()
    try:
        cur.execute("UPDATE menu SET Name = %s, Price = %s WHERE Menu_ID = %s", (new_name, new_price, menu_id))
        mysql.connection.commit()
        flash(f"Menu item {menu_id} updated.", "success")
    except Exception as e:
        mysql.connection.rollback()
        flash(f"Failed to update item: {e}", "error")
    cur.close()
    return redirect(url_for('menu_page'))


@app.route('/delete_menu/<int:menu_id>', methods=['POST'])
def delete_menu_item(menu_id):
    cur = mysql.connection.cursor()
    try:
        cur.execute("DELETE FROM menu WHERE Menu_ID = %s", (menu_id,))
        mysql.connection.commit()
        flash(f"Menu item {menu_id} deleted.", "success")
    except Exception as e:
        mysql.connection.rollback()
        flash(f"Failed to delete item: {e}", "error")
    cur.close()
    return redirect(url_for('menu_page'))



if __name__ == '__main__':
    app.run(debug=True)




